#!/usr/bin/env python3
"""
Repack an Android boot image (header v0-v2) with a new kernel, preserving the
ramdisk, DTB and AVB signing.

Usage:
    repack_boot.py <new-kernel> <source-boot.img> <out-boot.img> [avbtool.py]

The new kernel may be either an uncompressed arm64 Image or an Image.gz/lz4;
the Android boot header has no compression field, so whatever you pass is
written verbatim into the kernel slot.

Two things happen here:

1.  The Android boot image is reassembled: header + kernel + ramdisk +
    (recovery_dtbo) + DTB, with the header sizes and the AOSP image id
    (SHA-1) recomputed.

2.  AVB is rebuilt. This is REQUIRED, not cosmetic:

    the embedded vbmeta struct (the "AVB0" blob) sits inside the image,
    immediately after the kernel/ramdisk/DTB body, and the AVB footer at the
    very end of the image points at it. Replacing the kernel changes the body
    length, so the vbmeta struct moves. Copying the old AVB area (as the first
    version of this script did) leaves the footer pointing at stale bytes and
    the image fails verification:

        avbtool info_image --image boot.img
        -> "Given image does not look like a vbmeta image"

    That is a boot loop on a device that verifies the boot partition.

    The AVB parameters of the source image (salt, partition name, hash
    algorithm, rollback index, properties) are read back with avbtool and used
    to re-sign the new body, so the result verifies exactly like the original.

If avbtool is not available (or the source image has no AVB footer), the
script falls back to producing an unsigned image and says so loudly.
"""
import os
import shutil
import struct
import tempfile
import subprocess
import sys

MAGIC = b'ANDROID!'


class BootImage:
    def __init__(self, blob):
        self.blob = bytearray(blob)
        if self.blob[:8] != MAGIC:
            raise ValueError('not an Android boot image (bad magic)')

        self.page = self.u32(36)
        self.header_version = self.u32(40)
        if self.page == 0 or (self.page & (self.page - 1)) != 0:
            raise ValueError('invalid page size %r' % self.page)
        if self.header_version not in (0, 1, 2):
            raise ValueError('unsupported header version %r' % self.header_version)

        self.ksize = self.u32(8)
        self.rsize = self.u32(16)
        self.ssize = self.u32(24)

        if self.header_version >= 1:
            self.rdtbo_size = self.u32(1632)
            self.rdtbo_off = struct.unpack('<Q', self.blob[1636:1644])[0]
            self.header_size = self.u32(1644)
        else:
            self.rdtbo_size = 0
            self.rdtbo_off = 0
            self.header_size = 0

        if self.header_version >= 2:
            self.dtb_size = self.u32(1648)
            self.dtb_addr = struct.unpack('<Q', self.blob[1652:1660])[0]
        else:
            self.dtb_size = 0
            self.dtb_addr = 0

    def u32(self, off):
        return struct.unpack('<I', self.blob[off:off + 4])[0]

    def set_u32(self, off, val):
        self.blob[off:off + 4] = struct.pack('<I', val)

    @staticmethod
    def _pages(n, page):
        return (n + page - 1) // page

    def layout(self):
        page = self.page
        ko = page
        ro = ko + self._pages(self.ksize, page) * page
        so = ro + self._pages(self.rsize, page) * page
        return ko, ro, so

    def extract_parts(self):
        ko, ro, so = self.layout()
        kernel = bytes(self.blob[ko:ko + self.ksize])
        ramdisk = bytes(self.blob[ro:ro + self.rsize])
        second = bytes(self.blob[so:so + self.ssize])

        cur = so + self._pages(self.ssize, self.page) * self.page
        rdtbo = b''
        if self.rdtbo_size:
            rdtbo = bytes(self.blob[self.rdtbo_off:self.rdtbo_off + self.rdtbo_size])
            rdtbo_page_end = self.rdtbo_off + self._pages(self.rdtbo_size, self.page) * self.page
            cur = max(cur, rdtbo_page_end)
        dtb = b''
        if self.dtb_size:
            dtb = bytes(self.blob[cur:cur + self.dtb_size])
        return kernel, ramdisk, second, rdtbo, dtb

    def image_id(self, kernel, ramdisk, second, rdtbo=b'', dtb=b''):
        """AOSP boot image id (header v2), mirroring mkbootimg get_image_id()."""
        import hashlib
        h = hashlib.sha1()
        for part in (kernel, ramdisk, second, rdtbo, dtb):
            h.update(part)
            h.update(struct.pack('<I', len(part)))
        return h.digest()

    def repack(self, new_kernel):
        _, ramdisk, second, rdtbo, dtb = self.extract_parts()
        page = self.page

        self.ksize = len(new_kernel)
        self.set_u32(8, self.ksize)

        out = bytearray()
        out += self.blob[:page]

        def pad_to_page(buf):
            rem = len(buf) % page
            if rem:
                buf += b'\x00' * (page - rem)
            return buf

        out += pad_to_page(bytearray(new_kernel))
        out += pad_to_page(bytearray(ramdisk))
        out += pad_to_page(bytearray(second))

        if self.header_version >= 1 and rdtbo:
            new_off = len(out)
            self.set_u32(1632, len(rdtbo))
            self.blob[1636:1644] = struct.pack('<Q', new_off)
            out += pad_to_page(bytearray(rdtbo))
        elif self.header_version >= 1:
            self.set_u32(1632, 0)
            self.blob[1636:1644] = struct.pack('<Q', 0)

        if self.header_version >= 2 and dtb:
            self.set_u32(1648, len(dtb))
            out += pad_to_page(bytearray(dtb))
        elif self.header_version >= 2:
            self.set_u32(1648, 0)

        out[0:page] = bytearray(self.blob[:page])

        image_id = self.image_id(bytes(new_kernel), ramdisk, second, rdtbo, dtb)
        out[576:596] = image_id
        out[596:608] = b'\x00' * 12

        return bytes(out)


def avbtool_info(avbtool, image):
    """Return avbtool info_image output, or None if the image has no AVB."""
    try:
        out = subprocess.run(
            [sys.executable, avbtool, 'info_image', '--image', image],
            capture_output=True, text=True, check=False)
    except OSError:
        return None
    if out.returncode != 0:
        return None
    return out.stdout


def parse_field(text, label):
    for line in text.splitlines():
        if label in line:
            return line.split(label, 1)[1].strip()
    return None


def parse_avb_params(info):
    """Extract the AVB parameters needed to re-sign the image."""
    params = {}
    salt = parse_field(info, 'Salt:')
    if salt:
        params['salt'] = salt
    algo = parse_field(info, 'Hash Algorithm:')
    if algo:
        params['hash_algorithm'] = algo
    rollback = parse_field(info, 'Rollback Index:')
    if rollback and rollback != '0':
        params['rollback_index'] = rollback

    props = []
    for line in info.splitlines():
        line = line.strip()
        if line.startswith('Prop:'):
            kv = line[len('Prop:'):].strip()
            if ' -> ' in kv:
                key, val = kv.split(' -> ', 1)
                val = val.strip()
                if len(val) >= 2 and val[0] == "'" and val[-1] == "'":
                    val = val[1:-1]
                props.append((key.strip(), val))
    params['props'] = props
    return params


def main():
    if len(sys.argv) not in (4, 5):
        print(__doc__)
        return 1
    kernel_path, boot_path, out_path = sys.argv[1:4]
    avbtool = sys.argv[4] if len(sys.argv) == 5 else 'avbtool.py'
    if not os.path.exists(avbtool):
        avbtool = shutil.which('avbtool') or avbtool

    new_kernel = open(kernel_path, 'rb').read()
    source_blob = open(boot_path, 'rb').read()
    img = BootImage(source_blob)
    print('source boot : header v%d, page=%d, kernel=%d, ramdisk=%d, dtb=%d'
          % (img.header_version, img.page, img.ksize, img.rsize, img.dtb_size))
    print('new kernel  : %d bytes' % len(new_kernel))

    body = img.repack(new_kernel)
    print('new body    : %d bytes' % len(body))

    info = avbtool_info(avbtool, boot_path)
    if not info:
        print('WARNING: source has no AVB footer (or avbtool missing):')
        print('         writing an UNSIGNED image.')
        with open(out_path, 'wb') as f:
            f.write(body)
        return 0

    params = parse_avb_params(info)
    partition_size = len(source_blob)

    # body must be written first; avbtool appends the vbmeta + footer in place
    with open(out_path, 'wb') as f:
        f.write(body)

    cmd = [sys.executable, avbtool, 'add_hash_footer',
           '--image', out_path,
           '--partition_name', 'boot',
           '--partition_size', str(partition_size)]
    if params.get('hash_algorithm'):
        cmd += ['--hash_algorithm', params['hash_algorithm']]
    if params.get('salt'):
        cmd += ['--salt', params['salt']]
    if params.get('rollback_index'):
        cmd += ['--rollback_index', params['rollback_index']]
    for key, val in params.get('props', []):
        cmd += ['--prop', '%s:%s' % (key, val)]

    print('AVB re-sign  : salt=%s props=%d partition_size=%d'
          % (params.get('salt', '-')[:16] + '...', len(params.get('props', [])),
             partition_size))
    res = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if res.returncode != 0:
        print('ERROR: avbtool add_hash_footer failed:', file=sys.stderr)
        print(res.stdout, file=sys.stderr)
        print(res.stderr, file=sys.stderr)
        return 1

    # verify. avbtool resolves hash-descriptor partitions by filename, so a
    # copy named after the partition (boot.img) must sit next to the image.
    ver_dir = tempfile.mkdtemp(prefix='avbverify-')
    ver_img = os.path.join(ver_dir, 'boot.img')
    shutil.copyfile(out_path, ver_img)
    ver = subprocess.run(
        [sys.executable, avbtool, 'verify_image', '--image', ver_img],
        capture_output=True, text=True, check=False)
    shutil.rmtree(ver_dir, ignore_errors=True)
    if ver.returncode != 0 or 'Successfully verified' not in ver.stdout:
        print('ERROR: re-signed image failed verification:', file=sys.stderr)
        print(ver.stdout, file=sys.stderr)
        print(ver.stderr, file=sys.stderr)
        return 1
    print('AVB verify   : OK')
    print('wrote %s (%d bytes)' % (out_path, os.path.getsize(out_path)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
