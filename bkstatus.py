#!/bin/env python3.9
import getopt
import os
import re
import sqlite3
import sys

import yaml

config = {
    'db': '/var/lib/backup/cycbackup.db',
}
exclude: list[re.Pattern] = []
db_conn: sqlite3.Connection

def check_excluded(fullname):
    global exclude
    for pt in exclude:
        if pt.search(fullname) is not None:
            print(f"{fullname} excluded by {pt.pattern}")


def show_excluded(dir):
    global config, exclude
    for item in config['exclude']:
        cp = re.compile(item)
        exclude.append(cp)
    for path, dirs, files in os.walk(dir):
        for item in files:
            fullname = os.path.join(path, item)
            check_excluded(fullname)
        for item in dirs:
            fullname = os.path.join(path, item, '')
            check_excluded(fullname)


def show_file_status(fullname):
    global db_conn
    row = db_conn.execute('select name,mtime,date  from files as f join backup as b on f.volume=b.num where f.name=?',(fullname,)).fetchone()
    if row is not None:
        print(f"{fullname} <- {row[2]}")
    else:
        print(f"{fullname} - not backed up")

def show_status():
    global db_conn
    with sqlite3.connect(config['db']) as db_conn:
        for path, dirs, files in os.walk(os.getcwd()):
            for item in files:
                fullname = os.path.join(path,item)
                show_file_status(fullname)


def main():
    global config
    opts, arg = getopt.getopt(sys.argv[1:], 'c:e:s')
    for opt, opt_arg in opts:
        if opt == '-c':
            with open(opt_arg) as cf:
                config.update(yaml.safe_load(cf))
        elif opt == '-e':
            show_excluded(opt_arg)
        elif opt=='-s':
            show_status()


if __name__ == '__main__':
    try:
        print(f"{sys.argv[0]} running")
        main()
    except Exception as ex:
        print(f"exception{ex}", file=sys.stderr)
    finally:
        print("all done")
