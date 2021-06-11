"""
Convert from old gallery software to new gallery.

Take raw album files and DB info, and translate into new dir structure.
"""

import argparse
import os
import logging

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
                if not self.is_visible(child_id):
                    continue
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
                    return '/'+'/'.join(reversed(path))

    def get_details(self, g_id):
        details = {}
        with self.connection.cursor() as cursor:
            sql = 'select g_title as title, g_keywords as keywords, g_summary as summary, g_description as description from g2_Item where g_id = %s'
            cursor.execute(sql, (g_id,))
            details.update(cursor.fetchone())

        details['path'] = self.build_path(g_id)

        return details

    def is_visible(self, g_id):
        with self.connection.cursor() as cursor:
            sql = 'select g_permission&1 as access from g2_AccessMap join g2_AccessSubscriberMap on g2_AccessSubscriberMap.g_accessListId = g2_AccessMap.g_accessListId where g2_AccessSubscriberMap.g_itemId = %s and g2_AccessMap.g_userOrGroupId in (4, 5)'
            cursor.execute(sql, (g_id,))
            return any(row['access'] for row in cursor.fetchall())

def main():
    config = {
        'MYSQL_HOST': '127.0.0.1',
        'MYSQL_USER': os.environ.get('MYSQL_USER', 'root'),
        'MYSQL_PASSWORD': os.environ.get('MYSQL_PASSWORD', 'admin'),
        'MYSQL_DBNAME': 'gallery2_internal',
    }
    parser = argparse.ArgumentParser()
    parser.add_argument('source')
    parser.add_argument('dest')
    args = parser.parse_args()
    connection = pymysql.connect(host=config['MYSQL_HOST'],
                             user=config['MYSQL_USER'],
                             password=config['MYSQL_PASSWORD'],
                             db=config['MYSQL_DBNAME'],
                             charset='utf8',
                             cursorclass=pymysql.cursors.DictCursor)

    db = DB(connection)

    from pprint import pprint

    #albums = db.get_children(db.get_root_album())
    albums = db.get_children(5421)
    print(albums)
    pprint([db.get_details(gid) for gid in albums])
    print(len(albums))



if __name__ == '__main__':
    main()