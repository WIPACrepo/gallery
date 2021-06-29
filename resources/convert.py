"""
Convert from old gallery software to new gallery.

Take raw album files and DB info, and translate into new dir structure.
"""

import argparse
import os
from collections import Counter
from pathlib import Path
import logging
import shutil
from html import unescape

import pymysql.cursors



class DB:
    ROOT_ALBUM = 7

    def __init__(self, connection):
        self.connection = connection

    def get_root_album(self):
        return DB.ROOT_ALBUM

    def get_children(self, g_id):
        with self.connection.cursor() as cursor:
            # get child ids
            sql = 'select g_id from g2_ChildEntity where g_parentId = %s'
            cursor.execute(sql, (g_id,))
            children = []
            for row in cursor.fetchall():
                child_id = row['g_id']
                #if not self.is_visible(child_id):
                #    continue
                children.append(child_id)

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

    def get_details(self, g_id):
        details = {'id': g_id}
        with self.connection.cursor() as cursor:
            sql = 'select g_title as Title, g_keywords as Keywords, g_summary as Summary, g_description as description from g2_Item where g_id = %s'
            cursor.execute(sql, (g_id,))
            details.update(cursor.fetchone())
            for k in list(details.keys()):
                if details[k] is None:
                    details[k] = ''

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


        details['path'] = self.build_path(g_id)
        details['hidden'] = not self.is_visible(g_id)

        return details

    def is_visible(self, g_id):
        with self.connection.cursor() as cursor:
            sql = 'select g_permission&1 as access from g2_AccessMap join g2_AccessSubscriberMap on g2_AccessSubscriberMap.g_accessListId = g2_AccessMap.g_accessListId where g2_AccessSubscriberMap.g_itemId = %s and g2_AccessMap.g_userOrGroupId in (4, 5)'
            cursor.execute(sql, (g_id,))
            return any(row['access'] for row in cursor.fetchall())

def write_md(args, details):
    suffix = ''
    if details['type'] == 'GalleryAlbumItem':
        path = Path(args.dest) / details['path'] / 'index.md'
    else:
        path = Path(args.dest) / details['path']
        suffix = ''.join(path.suffixes)
        if details['multiformat']:
            path = path.with_name(path.name.replace('.', '_') + suffix)
        if not path.exists():
            shutil.copy2(Path(args.source) / details['path'], path)
        path = path.with_name(path.name.replace(suffix, '') + '.md')

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w') as f:
        for k in details:
            if not k[0].islower():
                v = unescape(str(details[k]))
                print(f'{k}: {v}', file=f)

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
                print(f'Sort: {sort}', file=f)

        if 'thumbnails' in details and (details['type'] == 'GalleryAlbumItem'
                                        or suffix in ('.gif','.mp4','.avi','.webm','.mov')):
            if details['type'] == 'GalleryAlbumItem':
                thumb_path = Path(args.dest) / details['path'] / 'thumbnails/thumb.jpg'
            else:
                thumb_path = (Path(args.dest) / details['path']).parent / 'thumbnails' / Path(details['path']).name
                if suffix in ('.mp4','.avi','.webm','.mov'):
                    thumb_path.with_name(thumb_path.name.replace(suffix, '.jpg'))
            thumb_path.parent.mkdir(parents=True, exist_ok=True)
            if not thumb_path.exists():
                for p in details['thumbnails']:
                    path = Path(args.source) / p
                    if path.exists():
                        print(f'found thumb {path} {thumb_path}')
                        shutil.copy2(path, thumb_path)
                        break
                    path = Path(args.cache) / p
                    if path.exists():
                        print(f'found thumb {path} {thumb_path}')
                        shutil.copy2(path, thumb_path)
                        break
            if thumb_path.exists():
                print(f'Thumbnail: thumbnails/{thumb_path.name}', file=f)

        print('', file=f)
        if details['description']:
            print(f'{details["description"]}', file=f)


def main():
    config = {
        'MYSQL_HOST': '127.0.0.1',
        'MYSQL_USER': os.environ.get('MYSQL_USER', 'root'),
        'MYSQL_PASSWORD': os.environ.get('MYSQL_PASSWORD', 'admin'),
        'MYSQL_DBNAME': 'gallery2_internal',
    }
    parser = argparse.ArgumentParser()
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

    #print(db.build_path(326064))
    #print(db.get_details(326064))
    #return

    from pprint import pprint

    def process_path(path):
        path = os.path.join(root, path)[len(args.source)+1:]
        try:
            g_id = db.get_id_for_path(path)
        except Exception:
            print(f'{path} is missing')
            return
        details = db.get_details(g_id)
        if details['hidden']:
            print(f'{path} is hidden')
            return
        write_md(args, details)

    write_md(args, db.get_details(DB.ROOT_ALBUM))
    for root,dirs,files in os.walk(args.source):
        for path in dirs: # these should be albums
            process_path(path)
        for path in files: # these should be images/videos
            process_path(path)

    return

    g_id = db.get_id_for_path('222/Bootcamp/Bootcamp 2018/UWRiverFalls_bootcampparticipants.JPG')
    print(g_id, db.get_details(g_id))

    #albums = db.get_children(db.get_root_album())
    albums = db.get_children(5421)
    print(albums)
    pprint([db.get_details(gid) for gid in albums])
    print(len(albums))



if __name__ == '__main__':
    main()