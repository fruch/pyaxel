#!/usr/bin/env python
# -*- coding: utf-8 -*-

from pyaxel.axel import Axel


def test_axel():
    a = Axel("http://download.thinkbroadband.com/512MB.zip", count=10)
    a.fetch_n_stitch()
