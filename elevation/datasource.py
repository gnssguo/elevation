# -*- coding: utf-8 -*-
#
# Copyright (c) 2016 B-Open Solutions srl - http://bopen.eu
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# python 2 support via python-future
from __future__ import absolute_import, division, print_function, unicode_literals

import collections
import math
import os.path
import pkgutil

import appdirs

from . import util

# declare public all API functions and constants
__all__ = [
    'info', 'seed', 'clip', 'clean', 'distclean',
    'CACHE_DIR', 'DEFAULT_PRODUCT', 'PRODUCTS', 'DEFAULT_OUTPUT', 'MARGIN', 'TOOLS',
]

CACHE_DIR = appdirs.user_cache_dir('elevation', 'bopen')
DEFAULT_OUTPUT = 'out.tif'
MARGIN = '0'


def srtm1_tile_ilonlat(lon, lat):
    return int(math.floor(lon)), int(math.floor(lat))


def srtm3_tile_ilonlat(lon, lat):
    ilon, ilat = srtm1_tile_ilonlat(lon, lat)
    return (ilon + 180) // 5 + 1, (64 - ilat) // 5


def srtm1_tiles_names(left, bottom, right, top, tile_name_template='{slat}/{slat}{slon}.tif'):
    ileft, itop = srtm1_tile_ilonlat(left, top)
    iright, ibottom = srtm1_tile_ilonlat(right, bottom)
    # special case often used *integer* top and right to avoid downloading unneeded tiles
    if isinstance(top, int) or top.is_integer():
        itop -= 1
    if isinstance(right, int) or right.is_integer():
        iright -= 1
    for ilon in range(ileft, iright + 1):
        slon = '%s%03d' % ('E' if ilon >= 0 else 'W', abs(ilon))
        for ilat in range(ibottom, itop + 1):
            slat = '%s%02d' % ('N' if ilat >= 0 else 'S', abs(ilat))
            yield tile_name_template.format(**locals())


def srtm3_tiles_names(left, bottom, right, top, tile_template='srtm_{ilon:02d}_{ilat:02d}.tif'):
    ileft, itop = srtm3_tile_ilonlat(left, top)
    iright, ibottom = srtm3_tile_ilonlat(right, bottom)
    for ilon in range(ileft, iright + 1):
        for ilat in range(itop, ibottom + 1):
            yield tile_template.format(**locals())


DATASOURCE_MAKEFILE = pkgutil.get_data('elevation', 'datasource.mk').decode('utf-8')

SRTM1_SPEC = {
    'folders': ('spool', 'cache'),
    'file_templates': {'Makefile': DATASOURCE_MAKEFILE},
    'datasource_url': 'https://s3.amazonaws.com/elevation-tiles-prod/skadi',
    'tile_ext': '.hgt',
    'compressed_pre_ext': '.hgt',
    'compressed_ext': '.hgt.gz',
    'tile_names': srtm1_tiles_names,
}

SRTM3_SPEC = {
    'folders': ('spool', 'cache'),
    'file_templates': {'Makefile': DATASOURCE_MAKEFILE},
    'datasource_url': 'http://srtm.csi.cgiar.org/SRT-ZIP/SRTM_V41/SRTM_Data_GeoTiff',
    'tile_ext': '.tif',
    'compressed_pre_ext': '',
    'compressed_ext': '.zip',
    'tile_names': srtm3_tiles_names,
}

PRODUCTS_SPECS = collections.OrderedDict([
    ('SRTM1', SRTM1_SPEC),
    ('SRTM3', SRTM3_SPEC),
])

PRODUCTS = list(PRODUCTS_SPECS)
DEFAULT_PRODUCT = PRODUCTS[0]
TOOLS = [
    ('GNU Make', 'make --version'),
    ('curl', 'curl --version'),
    ('unzip', 'unzip -v'),
    ('gunzip', 'gunzip --version'),
    ('gdal_translate', 'gdal_translate --version'),
    ('gdalbuildvrt', 'gdalbuildvrt --version'),
]


def ensure_tiles(path, ensure_tiles_names=(), **kwargs):
    ensure_tiles = ' '.join(ensure_tiles_names)
    variables_items = [('ensure_tiles', ensure_tiles)]
    return util.check_call_make(path, targets=['download'], variables=variables_items, **kwargs)


# FIXME: force=True is an emergency hack to ensure that the file always contains the intended body
def ensure_setup(cache_dir, product, force=True):
    datasource_root = os.path.join(cache_dir, product)
    spec = PRODUCTS_SPECS[product]
    util.ensure_setup(datasource_root, product=product, force=force, **spec)
    return datasource_root, spec


def do_clip(path, bounds, output, **kwargs):
    left, bottom, right, top = bounds
    projwin = '%s %s %s %s' % (left, top, right, bottom)
    variables_items = [('output', output), ('projwin', projwin)]
    return util.check_call_make(path, targets=['clip'], variables=variables_items)


def seed(cache_dir=CACHE_DIR, product=DEFAULT_PRODUCT, bounds=None, max_donwload_tiles=9, **kwargs):
    datasource_root, spec = ensure_setup(cache_dir, product)
    ensure_tiles_names = list(spec['tile_names'](*bounds))
    # FIXME: emergency hack to enforce the no-bulk-download policy
    if len(ensure_tiles_names) > max_donwload_tiles:
        raise RuntimeError("Too many tiles: %d. Please consult the providers' websites "
                           "for how to bulk download tiles." % len(ensure_tiles_names))
    ensure_tiles(datasource_root, ensure_tiles_names, **kwargs)
    util.check_call_make(datasource_root, targets=['all'])
    return datasource_root


def build_bounds(bounds, margin=MARGIN):
    left, bottom, right, top = bounds
    if margin.endswith('%'):
        margin_percent = float(margin[:-1])
        margin_lon = (right - left) * margin_percent / 100
        margin_lat = (top - bottom) * margin_percent / 100
    else:
        margin_lon = margin_lat = float(margin)
    return (left - margin_lon, bottom - margin_lat, right + margin_lon, top + margin_lat)


def clip(bounds, output=DEFAULT_OUTPUT, margin=MARGIN, **kwargs):
    """Clip the DEM to given bounds.

    :param bounds: Output bounds in 'left bottom right top' order.
    :param output: Path to output file. Existing files will be overwritten.
    :param margin: Decimal degree margin added to the bounds. Use '%' for percent margin.
    :param cache_dir: Root of the DEM cache folder.
    :param product: DEM product choice.
    """
    bounds = build_bounds(bounds, margin=margin)
    datasource_root = seed(bounds=bounds, **kwargs)
    do_clip(datasource_root, bounds, output, **kwargs)


def info(cache_dir=CACHE_DIR, product=DEFAULT_PRODUCT, **kwargs):
    datasource_root, _ = ensure_setup(cache_dir, product)
    util.check_call_make(datasource_root, targets=['info'])


def clean(cache_dir=CACHE_DIR, product=DEFAULT_PRODUCT):
    """Clean up the cache from temporary files.

    :param cache_dir: Root of the DEM cache folder.
    :param product: DEM product choice.
    """
    datasource_root, _ = ensure_setup(cache_dir, product)
    util.check_call_make(datasource_root, targets=['clean'])


def distclean(cache_dir=CACHE_DIR, product=DEFAULT_PRODUCT):
    """Remove the tile cache entirely.

    :param cache_dir: Root of the DEM cache folder.
    :param product: DEM product choice.
    """
    datasource_root, _ = ensure_setup(cache_dir, product)
    util.check_call_make(datasource_root, targets=['distclean'])
