#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright 2012-2015 Matt Martz
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.
from __future__ import print_function

import argparse
import fileinput
import glob
import os
import signal
import sys
import time
import timeit

import requests
import tqdm
from gevent import monkey
from gevent.pool import Pool

monkey.patch_all()


def catch_ctrl_c(signum, frame):
    print()
    sys.exit(0)


class Axel(object):
    def __init__(self, url=None, count=8):
        signal.signal(signal.SIGINT, catch_ctrl_c)

        self.count = count
        self.url = url
        self.speed = 0
        self.total_time = 0

        self.content_length = 0
        self.start = 0
        self.startcount = []
        self.filename = None
        self.chunk_size = 0
        self.chunks = []
        self.files = []

    def parse_args(self):
        parser = argparse.ArgumentParser()
        parser.add_argument('url')
        parser.add_argument('-c', '--count', type=int, default=self.count)
        args = parser.parse_args()

        self.url = args.url
        self.count = args.count

        return args

    def get_file_info(self):
        r = requests.head(self.url)
        self.content_length = int(r.headers.get('Content-Length', 0))
        self.chunk_size = self.content_length / self.count
        for i in xrange(self.count):
            if i == self.count - 1:
                boundary = self.content_length
            else:
                boundary = ((i + 1) * self.chunk_size) - 1
            self.chunks.append((i * self.chunk_size, boundary))

        self.filename = os.path.basename(self.url)
        while os.path.isfile(self.filename):
            prefix, ext = os.path.splitext(self.filename)
            if ext[1:].isdigit():
                newext = int(ext[1:]) + 1
                self.filename = '%s.%s' % (prefix, newext)
            else:
                self.filename = '%s.0' % self.filename

    def resume_check(self):
        globs = glob.glob('%s.part*' % self.filename)
        if len(globs) == self.count:
            sizes = []
            new_chunks = []
            for i, f in enumerate(globs):
                sizes.append(os.path.getsize(f))
                if sizes[-1] == self.chunk_size:
                    new_chunks.append(None)
                    self.startcount.append(sizes[-1])
                elif (sizes[-1] != self.chunks[i][1] and
                        sizes[-1] < self.chunk_size):
                    new_chunks.append((
                        self.chunks[i][0] + sizes[-1],
                        ((i + 1) * self.chunk_size) - 1
                    ))
                    self.startcount.append(sizes[-1])
                else:
                    print('%s < %s' % (sizes[-1],
                                       self.chunks[i][1] - self.chunks[i][0]))
                    print('partial files already exist, and do not match the '
                          'size range')
                    print('    %s' % '\n    '.join(globs))
                    sys.exit(1)

            self.chunks[:] = new_chunks
            print('partial files already exist and match count (%s). There '
                  'is the posibility of creating a non working file. Please '
                  'check hashes after download completion\n' % self.count)
        elif globs:
            print('partial files already exist, and do not match the count '
                  '(%s) specified:' % self.count)
            print('    %s' % '\n    '.join(globs))
            print('\nTry setting --count %s' % len(globs))
            sys.exit(1)

    def print_start(self):
        print('Initializing download: %s' % self.url)
        print('File size: %s bytes' % self.content_length)
        print('Output file: %s' % self.filename)
        if self.startcount:
            print('Resuming download\n')
        else:
            print('Starting download\n')

    def getter(self, filename, chunk, bytecount):
        headers = {
            'Range': 'bytes=%s-%s' % chunk
        }
        r = requests.get(self.url, headers=headers, stream=True)
        with open(filename, 'a') as f:
            for block in r.iter_content(4096):
                if not block:
                    break
                bytecount.append(len(block))
                f.write(block)
                f.flush()

    def print_progress(self, pool, bytecount):
        self.last_total = sum(self.startcount)
        with tqdm.tqdm(initial=self.last_total, total=int(self.content_length),
                       unit_scale=True, unit="B") as pbar:
            while 1:
                time.sleep(0.1)

                total = float(sum(bytecount))
                t = int(total + sum(self.startcount)) - self.last_total
                if t > 0:
                    pbar.update(t)
                if not total:
                    continue

                if pool.free_count() == pool.size:
                    break

                self.last_total = int(total + sum(self.startcount))

    def fetch(self):
        if not self.content_length:
            self.get_file_info()
            self.resume_check()

        bytecount = []
        self.start = timeit.default_timer()
        p = Pool(size=self.count)

        pp = Pool(size=1)
        pp.spawn(self.print_progress, p, bytecount)

        for i, chunk in enumerate(self.chunks):
            self.files.append('%s.part%03d' % (self.filename, i))
            if not chunk:
                continue
            p.spawn(self.getter, self.files[-1], chunk, bytecount)

        p.join()

        self.total_time = timeit.default_timer() - self.start

        print()

    def stitch(self):
        with open(self.filename, 'w') as f:
            for block in fileinput.input(self.files, bufsize=4096):
                f.write(block)
                f.flush()

        for f in self.files:
            os.unlink(f)

    def fetch_n_stitch(self):
        self.fetch()
        self.stitch()

    def print_final(self):
        print('\nDownloaded %.00f MB in %.00f seconds. (%.02f MB/s)' %
              (self.content_length/1024**2,
               self.total_time,
               self.speed/1024**2))


def main():
    axel = Axel()
    axel.parse_args()
    axel.fetch_n_stitch()


if __name__ == "__main__":
    main()
