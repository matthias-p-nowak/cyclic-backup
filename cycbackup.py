#!/bin/env python3.9
"""
cyclic backup creating a tar file
"""
import datetime
import getopt
import logging
import os
import re
import sqlite3
import stat
import sys
import tarfile
import time
import traceback

import jinja2
import yaml

blocked = set()
config = {
    'db': 'cycbackup.db',
    'exclude': [],
    'flag': '.bkstop',
    'min_age': 300,
    'size': '50M',
    'target': '/tmp/backup.tar',
}
""" default config settings """
counts = {
    'backed_up': 0,
    'blocked': 0,
    'cyclic': 0,
    'device': 0,
    'excluded': 0,
    'incremental': 0,
    'permissions': 0,
    'removed': 0,
    'same_old': 0,
    'too_big': 0,
    'too_recent': 0,
}
db_conn: sqlite3.Connection
done = False
exclude = []
file_size = 0
max_age = 0
start_device: int
tar_file: tarfile.TarFile
target_size = 0
vol_num = 0

resultT = """
The counts are:

 backed up files:{{ "%7d" | format(backed_up) }}
     incremental:{{ "%7d" | format(incremental) }}
          cyclic:{{ "%7d" | format(cyclic) }}
skipped 2 recent:{{ "%7d" | format(too_recent) }}
 skipped as same:{{ "%7d" | format(same_old) }}
    skipped flag:{{ "%7d" | format(excluded) }}
   skipped perm.:{{ "%7d" | format(permissions) }}
 removed from db:{{ "%7d" | format(removed) }}
"""
""" template for the results """

def prep_database():
    """
    prepares the database, creates it if not exists
    """
    global db_conn, vol_num
    version: int = 0
    try:
        row = db_conn.execute('select max(version) from dbv').fetchone()
        if row is not None:
            version = row[0]
    except sqlite3.DatabaseError:
        logging.info('db has no version')
    if version == 0:
        logging.info("creating db from scratch")
        schema_stmts = [
            'CREATE TABLE files (name TEXT NOT NULL, mtime REAL NOT NULL,volume INTEGER)',
            'CREATE UNIQUE INDEX "prime" on files (name ASC)',
            'CREATE INDEX vols on files (volume ASC)',
            'CREATE TABLE backup (num INTEGER NOT NULL, date TEXT NOT NULL)',
            'CREATE INDEX bknum on backup (num ASC)',
            'CREATE TABLE dbv(version INTEGER NOT NULL)',
            'insert into dbv values(1)'
        ]
        for stmt in schema_stmts:
            db_conn.execute(stmt)
        db_conn.commit()
        logging.debug("upgraded from scratch")
    row = db_conn.execute('select max(volume) from files').fetchone()
    if row is not None and row[0] is not None:
        vol_num = row[0] + 1
    logging.debug(f"the current volume is {vol_num}")


def archive(fullname, inc):
    """
    archives one file if conditions are met
    :param fullname: full name of the file
    :param inc: apply rules for incremental backup
    """
    global exclude, counts, config, blocked, file_size, db_conn, vol_num
    for item in blocked:
        if fullname.startswith(item):
            counts['blocked'] += 1
            # logging.debug(f"blocked: {fullname}")
            return
    path=fullname
    while True:
        path,tail =os.path.split(path)
        if len(path)<=1:
            break
        try:
            if os.lstat(os.path.join(path, config['flag'])):
                logging.debug("found flag in path")
                blocked.add(path)
                return
        except FileNotFoundError as fnfe:
            pass
    try:
        stat_buf = os.lstat(fullname)
    except Exception as ex:
        logging.error(f"lstat({fullname}): {ex}")
        exc_type, exc_value, exc_traceback = sys.exc_info()
        for l in traceback.format_exception(exc_type, exc_value, exc_traceback):
            logging.warning(f"  {l.strip()}")
        return
    if stat.S_ISDIR(stat_buf.st_mode):
        ext_filename = fullname + '/'
    else:
        ext_filename = fullname
    for pt in exclude:
        if pt.search(ext_filename) is not None:
            counts['excluded'] += 1
            # logging.debug(f"excluded: {fullname}")
            return
    if fullname == config['db']:
        return
    if stat_buf.st_dev != start_device:
        counts['device'] += 1
        logging.debug(f"device: {fullname}")
        return
    # sockets are created by running programs
    if stat.S_ISSOCK(stat_buf.st_mode):
        return
    mtime = int(stat_buf.st_mtime)
    if mtime > max_age:
        counts['too_recent'] += 1
        logging.debug(f"too recent: {fullname}")
        return
    # checking age against database
    if inc:
        row = db_conn.execute('select mtime from files where name=?', (fullname,)).fetchone()
        if row is not None:
            if row[0] == mtime:
                counts['same_old'] += 1
                # logging.debug(f"same old: {fullname}")
                return
    if not os.access(fullname, os.R_OK):
        logging.warning('missing permissions: ' + fullname)
        counts['permissions'] += 1
        logging.debug(f"permissions: {fullname}")
        return
    nfs = file_size + 1536 + stat_buf.st_size
    if nfs >= target_size:
        counts['too_big'] += 1
        # logging.debug(f"too big: {fullname}")
        return
    if inc:
        counts['incremental'] += 1
        # logging.debug(f"incremental: {fullname}")
    else:
        counts['cyclic'] += 1
        # logging.debug(f"cyclic: {fullname}")
    try:
        tar_file.add(fullname, recursive=False)
        db_conn.execute('replace into files(name,mtime,volume) values(?,?,?)',
                        (fullname, mtime, vol_num))
        db_conn.commit()
        file_size=tar_file.fileobj.tell()
    except Exception as ex:
        logging.error(f"tar archive {ex}")
    counts['backed_up'] += 1


def incremental():
    """
    incremental part - saving newer files
    """
    global config, blocked, start_device
    for entry in config['backup']:
        try:
            stat_buf = os.lstat(entry)
            start_device = stat_buf.st_dev
            for path, dirs, files in os.walk(entry):
                for item in files:
                    if item == config['flag']:
                        blocked.add(path)
                        continue
                    fullname = os.path.join(path, item)
                    archive(fullname, True)
                    if file_size + 8096 > target_size:
                        return
                for item in dirs:
                    fullname = os.path.join(path, item)
                    archive(fullname, True)
                    if file_size + 8096 > target_size:
                        return
        except FileNotFoundError as fnfe:
            logging.error(f"backup entry {entry} not found:\n {fnfe}")


def cyclic():
    """
    cyclic part - saving old files
    """
    global config, db_conn
    rs = db_conn.execute('select name, volume  from files where volume < ? order by volume ASC', (vol_num,))
    while True:
        row = rs.fetchone()
        if row is None:
            return
        archive(row[0],False)
        if file_size + 8096 > target_size:
            return


def main():
    """
    use cycbackup {options}
    """
    global config, db_conn, tar_file, exclude, max_age, target_size, vol_num
    opts, arg = getopt.getopt(sys.argv[1:], 'c:it:h?')
    for opt, opt_arg in opts:
        if opt == '-c':
            with open(opt_arg) as cf:
                config.update(yaml.safe_load(cf))
        elif opt == '-i':
            yaml.safe_dump(config, sys.stderr)
        elif opt == '-t':
            config['target'] = opt_arg
        else:
            print(main.__doc__)
            sys.exit(0)
    config['db'] = os.path.abspath(config['db'])
    for pattern in config['exclude']:
        cp = re.compile(pattern)
        exclude.append(cp)
    max_age = time.time() - config['min_age']
    size_pat = re.compile('(\\d+)([kmgGM])')
    m = size_pat.search(config['size'])
    target_size = 50 * 1024 * 1024
    if m is not None:
        target_size = int(m.group(1))
        unit = m.group(2)
        if unit == 'k':
            target_size *= 1000
        elif unit == 'K':
            target_size *= 1024
        elif unit == 'm':
            target_size *= 1000000
        elif unit == 'M':
            target_size *= 1024 * 1024
        elif unit == 'g':
            target_size *= 1000 * 1000 * 1000
        elif unit == 'G':
            target_size *= 1024 * 1024 * 1024
    logging.debug(f"target size is {target_size}")
    with sqlite3.connect(config['db']) as db_conn:
        prep_database()
        now = datetime.datetime.now().strftime('%y-%m-%d_%H-%M-%S')
        db_conn.execute('insert into backup(num,date) values(?,?)', (vol_num, now))
        db_conn.commit()
        with tarfile.open(config['target'], 'w:') as tar_file:
            incremental()
            cyclic()
    templ = jinja2.Template(resultT)
    result_txt = templ.render(counts)
    logging.debug(result_txt)
    print(result_txt)


if __name__ == '__main__':
    try:
        print(f"{sys.argv[0]} running")
        logging.basicConfig(filename='cycbackup.log', level=logging.DEBUG, filemode='w',
                            format='%(asctime)s [%(levelname)s] %(filename)s:%(lineno)d %(funcName)s:\t%(message)s')
        main()
    except Exception as ex:
        logging.error(f"main exception {ex}")
        traceback.print_exc()
    finally:
        print("all done")
