"""
Convert from old gallery software to new gallery.

Take raw album files and DB info, and translate into new dir structure.
"""

import argparse
import json
import os
from io import StringIO
from collections import Counter
from functools import cached_property
import logging
from pathlib import Path
from pprint import pprint
import shutil
import subprocess
from html import unescape

import pymysql.cursors



class DB:
    ROOT_ALBUM = 7

    def __init__(self, connection):
        self.connection = connection

    def get_root_album(self):
        return DB.ROOT_ALBUM

    def get_children(self, g_id, order=True):
        with self.connection.cursor() as cursor:
            # get child ids
            sql = 'select g_id from g2_ChildEntity where g_parentId = %s'
            cursor.execute(sql, (g_id,))
            children = []
            for row in cursor.fetchall():
                child_id = row['g_id']
                #if not self.is_visible(child_id):
                #    continue
                if self.get_type(child_id) not in ('GalleryAlbumItem','GalleryLinkItem','GalleryPhotoItem',
                                                   'GalleryMovieItem','GalleryAnimationItem','GalleryUnknownItem'):
                    continue
                children.append(child_id)

            if order:
                # get order of parent
                sql = 'select * from g2_AlbumItem where g_id = %s'
                cursor.execute(sql, (g_id,))
                row = cursor.fetchone()

                # now order children
                if row['g_orderBy'] in ('NULL', '', None, 'RatingSortOrder'):
                    return children
                elif row['g_orderBy'] == 'orderWeight':
                    sql = 'select g_itemId as id from g2_ItemAttributesMap where g_itemId in ('
                    sql += ','.join('%s' for _ in children)
                    sql += ') order by g_orderWeight'
                elif row['g_orderBy'] == 'originationTimestamp':
                    sql = 'select g_id as id from g2_Item where g_id in ('
                    sql += ','.join('%s' for _ in children)
                    sql += ') order by g_originationTimestamp'
                elif row['g_orderBy'] == 'creationTimestamp':
                    sql = 'select g_id as id from g2_Entity where g_id in ('
                    sql += ','.join('%s' for _ in children)
                    sql += ') order by g_creationTimestamp'
                elif row['g_orderBy'] == 'albumsFirst|creationTimestamp':
                    sql = 'select g_id as id from g2_Entity where g_id in ('
                    sql += ','.join('%s' for _ in children)
                    sql += ') order by g_entityType,g_creationTimestamp'
                elif row['g_orderBy'] == 'title':
                    sql = 'select g_id as id from g2_Item where g_id in ('
                    sql += ','.join('%s' for _ in children)
                    sql += ') order by g_title'
                else:
                    raise Exception(f"unknown order by: {row['g_orderBy']}")
                cursor.execute(sql, children)
                children = [row['id'] for row in cursor.fetchall()]
                if row['g_orderDirection'] == 'desc':
                    children.reverse()
            return children

    def build_path(self, g_id):
        if g_id == DB.ROOT_ALBUM:
            return ''
        path = []
        with self.connection.cursor() as cursor:
            link_id = True
            while link_id:
                sql = 'select g_linkId from g2_Entity where g_id = %s'
                cursor.execute(sql, (g_id,))
                link_id = cursor.fetchone()['g_linkId']
                if link_id:
                    g_id = link_id
            while True:
                sql = 'select g_pathComponent from g2_FileSystemEntity where g_id = %s'
                cursor.execute(sql, (g_id,))
                p = cursor.fetchone()['g_pathComponent']
                if not p:
                    raise Exception(f'path missing for g_id {g_id}')
                path.append(p)

                sql = 'select g_parentId from g2_ChildEntity where g_id = %s'
                cursor.execute(sql, (g_id,))
                g_id = cursor.fetchone()['g_parentId']

                if g_id == DB.ROOT_ALBUM:
                    return '/'.join(reversed(path))

    def multi_format(self, g_id):
        """Test if there are multiple formats of this file"""
        with self.connection.cursor() as cursor:
            sql = 'select g_pathComponent from g2_FileSystemEntity where g_id = %s'
            cursor.execute(sql, (g_id,))
            p = cursor.fetchone()['g_pathComponent']
            if not p:
                raise Exception(f'path missing for g_id {g_id}')

            sql = 'select g_parentId from g2_ChildEntity where g_id = %s'
            cursor.execute(sql, (g_id,))
            g_id = cursor.fetchone()['g_parentId']

            sql = 'select g_pathComponent from g2_FileSystemEntity where g_id in (select g_id from g2_ChildEntity where g_parentId = %s)'
            cursor.execute(sql, (g_id,))
            children = Counter(Path(row['g_pathComponent']).stem for row in cursor.fetchall())
            return children[Path(p).stem] > 1

    def get_id_for_path(self, path):
        path = path.split('/')
        if path[0] == 'albums':
            path = path[1:]
        with self.connection.cursor() as cursor:
            g_id = DB.ROOT_ALBUM
            for p in path:
                sql = 'select g_id from g2_ChildEntity where g_parentId = %s'
                cursor.execute(sql, (g_id,))
                children = [row['g_id'] for row in cursor.fetchall()]
                if not children:
                    raise Exception(f'no children for g_id {g_id}')

                sql = 'select g_id,g_pathComponent from g2_FileSystemEntity where g_id in ('
                sql += ','.join('%s' for _ in children)
                sql += ')'
                cursor.execute(sql, children)
                for row in cursor.fetchall():
                    if row['g_pathComponent'] == p:
                        g_id = row['g_id']
                        break
                else:
                    raise Exception(f'did not find path {p} in g_id {g_id}')
            return g_id

    def get_type(self, g_id):
        with self.connection.cursor() as cursor:
            sql = 'select g_entityType as type from g2_Entity where g_id = %s'
            cursor.execute(sql, (g_id,))
            row = cursor.fetchone()
            return row['type']
    
    @cached_property
    def users(self):
        ret = {}
        with self.connection.cursor() as cursor:
            sql = 'select g_id, g_userName as username, g_fullName as name from g2_User'
            cursor.execute(sql)
            for row in cursor.fetchall():
                ret[row['g_id']] = {
                    'Username': row['username'],
                    'User_fullname': row['name'],
                }
        return ret

    def get_details(self, g_id):
        details = {'id': g_id}
        with self.connection.cursor() as cursor:
            sql = 'select g_title as Title, g_keywords as Keywords, g_summary as Summary, g_description as description, g_ownerId as owner from g2_Item where g_id = %s'
            cursor.execute(sql, (g_id,))
            ret = cursor.fetchone()
            g_owner_id = ret.pop('owner', -1)
            details.update(ret)
            for k in list(details.keys()):
                if details[k] is None:
                    details[k] = ''

            details.update(self.users.get(g_owner_id, {}))

            sql = 'select g_creationTimestamp as CreateDate, g_modificationTImestamp as ModDate, g_entityType as type from g2_Entity where g_id = %s'
            cursor.execute(sql, (g_id,))
            details.update(cursor.fetchone())

            if details['type'] == 'GalleryLinkItem':
                # is a link to an album
                sql = 'select g_link from g2_LinkItem where g_id = %s'
                cursor.execute(sql, (g_id,))
                g_id = cursor.fetchone()['g_link']
                details['link_id'] = g_id
                details['Link'] = '/'+self.build_path(g_id)

                sql = 'select g_creationTimestamp as CreateDate, g_modificationTImestamp as ModDate, g_entityType as type from g2_Entity where g_id = %s'
                cursor.execute(sql, (g_id,))
                details.update(cursor.fetchone())

            sql = 'select g_viewCount as Views, g_orderWeight as OrderWeight from g2_ItemAttributesMap where g_itemId = %s'
            cursor.execute(sql, (g_id,))
            details.update(cursor.fetchone())

            if not details['Keywords']:
                sql = 'select g_tagName from g2_TagMap join g2_TagItemMap on g2_TagMap.g_tagId = g2_TagItemMap.g_tagId where g_itemId = %s'
                cursor.execute(sql, (g_id,))
                details['Keywords'] = ', '.join(row['g_tagName'] for row in cursor.fetchall())

            if details['type'] == 'GalleryAlbumItem':
                # get order details
                sql = 'select g_orderBy as `sort`, g_orderDirection as `order` from g2_AlbumItem where g_id = %s'
                cursor.execute(sql, (g_id,))
                details.update(cursor.fetchone())
            else:
                # is a file
                details['multiformat'] = self.multi_format(g_id)

            # get thumbnail
            sql = 'select g_id from g2_ChildEntity where g_parentId = %s'
            cursor.execute(sql, (g_id,))
            children = [row['g_id'] for row in cursor.fetchall()]
            if children:
                sql = 'select g_id,g_entityType from g2_Entity where g_id in ('
                sql += ','.join('%s' for _ in children)
                sql += ')'
                cursor.execute(sql, children)
                thumb_id = None
                deriv_id = None
                for row in cursor.fetchall():
                    if row['g_entityType'] == 'ThumbnailImage':
                        thumb_id = row['g_id']
                        break
                    elif row['g_entityType'] == 'GalleryDerivativeImage':
                        deriv_id = row['g_id']
                if thumb_id:
                    details['thumbnails'] = [self.build_path(thumb_id)]
                    sql = 'select g_id from g2_Derivative where g_derivativeSourceId = %s'
                    cursor.execute(sql, (thumb_id,))
                    try:
                        deriv_id = cursor.fetchone()['g_id']
                    except Exception:
                        pass
                    else:
                        details['thumbnails'].append(f'derivative/{str(deriv_id)[0]}/{str(deriv_id)[1]}/{deriv_id}.dat')
                elif deriv_id:
                    details['thumbnails'] = [f'derivative/{str(deriv_id)[0]}/{str(deriv_id)[1]}/{deriv_id}.dat']


        details['src_path'] = self.build_path(g_id)
        details['path'] = self.build_path(details['id'])
        details['hidden'] = not self.is_visible(details['id'])

        return details

    def is_visible(self, g_id):
        with self.connection.cursor() as cursor:
            sql = 'select g_permission&1 as access from g2_AccessMap join g2_AccessSubscriberMap on g2_AccessSubscriberMap.g_accessListId = g2_AccessMap.g_accessListId where g2_AccessSubscriberMap.g_itemId = %s and g2_AccessMap.g_userOrGroupId in (4, 5)'
            cursor.execute(sql, (g_id,))
            return any(row['access'] for row in cursor.fetchall())


def needs_reorientation(path):
    try:
        out = subprocess.check_output(['identify', '-quiet', '-format', '%[orientation]', str(path)], stderr=subprocess.DEVNULL)
        return not any(x in out for x in [b'Undefined', b'Unrecognized', b'TopLeft'])
    except Exception:
        return False


def read_metadata(path):
    ret = {'title': '', 'keywords': '', 'summary': '', 'description': ''}
    if path.exists():
        with open(path) as f:
            ret.update(json.load(f))
    return ret


def write_metadata(path, data):
    ret = {'title': '', 'keywords': '', 'summary': '', 'description': ''}
    ret.update(data)
    with open(path, 'w') as f:
        json.dump(ret, f, ensure_ascii=False, indent=2)


def write_md(args, details):
    src_path = Path(args.source) / details['src_path']
    if not src_path.exists():
        if details['src_path'].startswith('SPImages/amanda'):
            details['src_path'] = details['src_path'].replace('SPImages/amanda','Archive/amanda')
            details['path'] = details['path'].replace('SPImages/amanda','Archive/amanda')
        elif details['path'].startswith('222 Frames'):
            details['src_path'] = 'WIPAC/' + details['src_path']
            details['path'] = 'WIPAC/' + details['path']
        elif details['src_path'].startswith('GraphicRe/promo/archive'):
            details['src_path'] = details['src_path'].replace('GraphicRe/promo/archive','GraphicRe/archive')
            details['path'] = details['path'].replace('GraphicRe/promo/archive','GraphicRe/archive')
        elif details['path'].startswith('222') and (Path(args.source) / '222' / 'Archive' / src_path.relative_to(Path(args.source) / '222')).exists():
            details['src_path'] = str(Path('222') / 'Archive' / src_path.relative_to(Path(args.source) / '222'))
            details['path'] = details['path'].replace('222/', '222/Archive/')
        elif (Path(args.source) / 'Archive' / details['src_path']).exists():
            details['src_path'] = 'Archive/' + details['src_path']
            details['path'] = 'Archive/' + details['path']
        elif (Path(args.source) / 'SPImages' / details['src_path']).exists():
            details['src_path'] = 'SPImages/' + details['src_path']
            details['path'] = 'SPImages/' + details['path']
        else:
            raise OSError(f'{src_path} does not exist')
        src_path = Path(args.source) / details['src_path']

    dest_path = Path(args.dest) / details['path']
    suffix = ''
    if details['type'] == 'GalleryAlbumItem':
        path = Path(args.dest) / details['path'] / 'index.meta.json'
    else:
        suffix = ''.join(dest_path.suffixes).lower()
        if 'multiformat' in details and details['multiformat']:
            dest_path = dest_path.with_name(dest_path.name.replace('.', '_') + suffix)
        if not dest_path.exists():
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            if dest_path.suffix.lower() in ('.jpg', '.png'):
                if needs_reorientation(src_path):
                    subprocess.check_call(['convert', src_path, '-auto-orient', dest_path])
                elif args.symlink:
                    dest_path.symlink_to(src_path)
                else:
                    shutil.copy2(src_path, dest_path)
            else:
                if args.symlink:
                    dest_path.symlink_to(src_path)
                else:
                    shutil.copy2(src_path, dest_path)
        path = dest_path.with_name(dest_path.name.replace(suffix, '') + '.meta.json')

    assert path.name.endswith('.meta.json')

    metadata = {}
    for k in details:
        if not k[0].islower():
            v = unescape(str(details[k]))
            metadata[k.lower()] = v

    if details['type'] == 'GalleryAlbumItem' and details['sort']:
        sort = None
        if details['sort'] == 'orderWeight':
            sort = 'meta.orderweight'
        elif 'Timestamp' in details['sort']:
            sort = 'meta.moddate'
        elif details['sort'] == 'title':
            sort = 'meta.title'
        else:
            sort = 'meta.orderweight'
        if sort:
            if details['order'] == 'desc':
                sort = '-'+sort
            metadata['sort'] = sort

    # generate thumbnail
    if details['type'] == 'GalleryAlbumItem':
        thumb_path = dest_path / 'thumbnails/thumb.jpg'
    else:
        thumb_path = dest_path.parent / 'thumbnails' / Path(details['path']).name
        if suffix in ('.mp4','.avi','.webm','.mov'):
            thumb_path = thumb_path.with_suffix('.jpg')

    if 'thumbnails' in details and (details['type'] == 'GalleryAlbumItem'
                                    or suffix not in ('.jpg','.jpeg','.png')):
        thumb_path.parent.mkdir(parents=True, exist_ok=True)
        if not thumb_path.exists():
            for p in details['thumbnails']:
                thumb_path_try = Path(args.source) / p
                if thumb_path_try.exists() and thumb_path_try.stat().st_size > 0:
                    print(f'found thumb {thumb_path_try} {thumb_path}')
                    if thumb_path_try.suffix.lower() in ('.jpg', '.jpeg', '.png'):
                        subprocess.check_call(['convert', thumb_path_try, '-auto-orient', thumb_path])
                    else:
                        shutil.copy2(thumb_path_try, thumb_path)
                    break
                thumb_path_try = Path(args.cache) / p
                if thumb_path_try.exists() and thumb_path_try.stat().st_size > 0:
                    print(f'found thumb {thumb_path_try} {thumb_path}')
                    if thumb_path_try.suffix.lower() in ('.jpg', '.png'):
                        subprocess.check_call(['convert', thumb_path_try, '-auto-orient', thumb_path])
                    else:
                        shutil.copy2(thumb_path_try, thumb_path)
                    break
        if thumb_path.exists():
            metadata['thumbnail'] = f'thumbnails/{thumb_path.name}'

    if 'thumbnail' not in metadata and dest_path.suffix.lower() in ('.jpg','.jpeg','.png'):
        if not thumb_path.exists():
            print(f'generating thumbnail for {dest_path}')
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            subprocess.check_call(['convert', dest_path, '-resize', '150x150', '-auto-orient', thumb_path])
        if thumb_path.exists():
            metadata['thumbnail'] = f'thumbnails/{thumb_path.name}'

    if details['description']:
        metadata['description'] = details["description"]

    existing_data = read_metadata(path)
    if existing_data != metadata:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_metadata(path, metadata)
    else:
        print(f'metadata already exists at {path}')


def main():
    config = {
        'MYSQL_HOST': '127.0.0.1',
        'MYSQL_USER': os.environ.get('MYSQL_USER', 'root'),
        'MYSQL_PASSWORD': os.environ.get('MYSQL_PASSWORD', 'admin'),
        'MYSQL_DBNAME': 'gallery2_internal',
    }
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-symlink', dest='symlink', default=True, action='store_false', help='use copy instead of symlink')
    parser.add_argument('source')
    parser.add_argument('cache')
    parser.add_argument('dest')
    args = parser.parse_args()
    connection = pymysql.connect(host=config['MYSQL_HOST'],
                             user=config['MYSQL_USER'],
                             password=config['MYSQL_PASSWORD'],
                             db=config['MYSQL_DBNAME'],
                             charset='utf8',
                             cursorclass=pymysql.cursors.DictCursor)

    db = DB(connection)

    paths = set()

    ### try DB traversal first
    def process_children(g_id):
        details = db.get_details(g_id)
        #pprint(details)
        if details['hidden'] and 'PersonalFiles' in details['path']:
            print(f'{details["path"]} is hidden')
            return
        if ('Thumbs_db' in details['path'] or '.AppleDouble' in details['path'] or '_DS_Store' in details['path'] or
            details['path'].endswith('drilldeploy/Season 6/String 81/IMG_6053.JPG') or
            details['path'].endswith('drilldeploy/Season 6/String 81/IMG_6052.JPG') or
            details['path'].endswith('drilldeploy/Season 6/String 81/IMG_6051.JPG') or
            details['path'].endswith('drilldeploy/Season 6/String 81/IMG_6050.JPG') or
            details['path'].endswith('drilldeploy/Season 6/String 81/IMG_6049.JPG') or
            details['path'].endswith('drilldeploy/Season 6/String 81/IMG_6048.JPG') or
            details['path'].endswith('drilldeploy/Season 6/String 81/IMG_6047.JPG') or
            details['path'].endswith('drilldeploy/Season 6/String 81/IMG_6046.JPG') or
            details['path'].endswith('drilldeploy/Season 6/String 81/IMG_6045.JPG') or
            details['path'].endswith('drilldeploy/Season 6/String 81/IMG_6044.JPG') or
            details['path'].endswith('drilldeploy/Season 6/String 81/IMG_6043.JPG') or
            details['path'].endswith('drilldeploy/Season 6/String 81/IMG_6042.JPG') or
            details['path'].endswith('rpearson/Video/MMSDTrip.mov') or
            details['path'].endswith('PersonalFiles/csburreson/generator_side__1_.jpg') or
            details['path'].endswith('PersonalFiles/jcherwinka/SouthPole56/P2076842.JPG')
            ):
            print(f'{details["path"]} is excluded')
            return
        name = Path(details['path']).name
        if name.startswith('__') or name == '_AppleDouble':
            print(f'{details["path"]} starts with __')
            return

        try:
            write_md(args, details)
        except Exception:
            if (details['path'].startswith('malkus/psl/Bander')
                or details['path'].startswith('SPImages/weekly/')
                or details['path'] == 'drilldeploy/Season 6/String 81/IMG_6043.JPG'):
                print(f'{details["path"]} is missing from fs')
                return
            pprint(details)
            raise

        paths.add(details['path'])

        for ch_id in db.get_children(g_id, order=False):
            try:
                process_children(ch_id)
            except Exception:
                print(f'Error processing gid {g_id} child {ch_id} - {details["path"]}')
                raise

    process_children(db.get_root_album())

    ### try filesystem traversal second
    def process_path(path):
        orig_path = path
        path = path[len(args.source)+1:]
        if path in paths:
            return True # already processed
        name = Path(path).name
        if 'Thumbs_db' in path or '.AppleDouble' in path or '_DS_Store' in path:
            print(f'{path} is excluded')
            return False
        if ((name.startswith('__') and path not in ('Archive/koci/Koci_s Slides/No Date/_______I-F-2-2_Electro-Mech_Drill.jpg',))
            or name == '_AppleDouble'):
            print(f'{path} starts with _')
            return False
        if (not Path(orig_path).exists()) and Path(orig_path).is_symlink():
            print(f'{path} is symlink to unknown fs')
            return False
        if os.path.getsize(orig_path) == 0:
            print(f'{path} is 0 bytes')
            return False
        try:
            g_id = db.get_id_for_path(path)
        except Exception:
            if path in ('SPImages/icl/icl_002/dc/cables/img_3661.jpg',
                        'SPImages/weekly/2012/IMG_0273_001.jpg',
                        'SPImages/weekly/2018/2018week35_raydome_001.jpg',
                        'SPImages/weekly/2018/2018week35_explosion_001.jpg',
                        'SPImages/weekly/2018/2018week35_soda_001.jpg',
                        'SPImages/weekly/2018/2018week35_dragon_001.jpg',
                        'SPImages/weekly/2018/2018week35_station_001.jpg',
                        'logos/uwmadison/color-UWcrest-print.pdf',
                        'GraphicRe/collabmaps/map_collaboration_031314_sm.jpg',
                        'GraphicRe/collabmaps/map_icecube-pingu_powerpoint_EUzoom_061614.jpg',
                        'GraphicRe/collabmaps/map_icecube-pingu_powerpoint_061614.jpg',
                        'GraphicRe/collabmaps/map_collaboration_powerpoint_EUzoom_031314_sm.jpg',
                        'Archive/malkus/Haugen 09-10/20091202 040.jpg',
                        'Archive/koci/Koci_s Slides/No Date/_______I-F-2-2_Electro-Mech_Drill.jpg',
                        ):
                # copy over anyway
                write_md(args, {'src_path': path, 'path': path, 'description': '', 'type': Path(path).suffix})
                return True
            if path in ('Archive/amanda',):
                return True
            if (path.startswith('Forest_ icecube') or path.lower().endswith('.jpg')
                or path.startswith('SPImages/ehwd')
                or path in {'logos/uwmadison/color-UWcrest-print.pdf'}
                ):
                print(f'{path} is missing from db')
                return False
            print(path)
            raise
        details = db.get_details(g_id)
        if details['hidden'] and 'PersonalFiles' in details['path']:
            print(f'{path} is hidden')
            return False
        write_md(args, details)
        return True

    for root,dirs,files in os.walk(args.source):
        for path in list(dirs): # these should be albums
            fullpath = os.path.join(root,path)
            partialpath = fullpath[len(args.source)+1:]
            if not list((Path(root) / path).iterdir()):
                print(f'{partialpath} is empty, skipping')
                dirs.remove(path)
                continue
            if (fullpath.endswith('SPImages/drilldeploy/drillinganddeployingteam/kxiong')
                or fullpath.endswith('Thumbs_db')
                or fullpath.endswith('.AppleDouble')
                or fullpath.endswith('_DS_Store')
                ):
                dirs.remove(path)
                continue
            if not process_path(fullpath):
                dirs.remove(path)
        for path in files: # these should be images/videos
            fullpath = os.path.join(root, path)
            if (fullpath.endswith('/Thumbs_db') or
                fullpath.endswith('/_DS_Store') or
                fullpath.endswith('SPImages/drilldeploy/Season 6/String 81/IMG_6045.JPG') or
                fullpath.endswith('SPImages/drilldeploy/Season 6/String 81/IMG_6044.JPG')
                ):
                continue
            process_path(fullpath)

    # clean up empty dirs
    for root,dirs,files in os.walk(args.dest):
        for path in list(dirs):
            fullpath = os.path.join(root, path)
            if os.listdir(fullpath) == ['index.meta.json']:
                print('cleaning up empty dir', fullpath)
                shutil.rmtree(fullpath)

if __name__ == '__main__':
    main()