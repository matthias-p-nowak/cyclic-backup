
# Backup
There are tape and disk based backup systems. 
The former combines a bunch of files into an archive format, which traditionally has been written on a tape medium.
The latter retrieves files from each client machine, discovers duplicates and stores the content on a server. 
Moreover, it needs to ensure protection against corruption and dangers.

The simplest form is tape based using *tar/rmt*. 
Usually, a full backup is taken once in a while. 
Then, files newer than the full backup (aka differential) or 
    newer than the last backup (aka incremental) are saved into smaller archives.

*Cyclic backup* is a python script that writes a *tar* archive up to a certain given size.
The first part is a incremental backup, the second phase is a partial full backup. 
This means, it archives files which were least recently backed up again.
In order to achieve this, *cycbackup.py* uses a Sqlite database.

## How it works

Steps:
* cycbackup reads a configuration file which specifies a database location (*db*), 
which item to back up and what to skip
* prints the used configuration (if option "-i" is given)
* in case the database (sqlite3) does not exist, it is created with the tables
* starts the incremental backup in the following step
* for each specified location (*backup*):
    * it looks for files that are newer than registered in the database
    * checks if they are too recent - *max_age* parameter controls that - they are skipped
    * checks if they match some exclusion patterns (*exclude*) - 
        **note:** that those are regular expressions, which must match parts of the filename
    * a *flag file* causes the directory and it's content to be excluded from backup
    * checks if the backup can access this file for reading
    * adds the file to the *tar* archive
* starts the cyclic backup in the following step
    * reads all files from the database, starting with the least recent backed up one
    * looks at the filesystem if it exists
        * in case it does not exist, it will be removed from the database
        * if it is excluded or too recent, it will be removed from the database
        * if it exists, it will be backed up
* it finishes with
    * writing statistics to the log file
    
## Configuration
~~~
---
backup:
- /tmp/2bk
db: cycbackup.db
exclude:
- /tt/
- /.git/
- /.settings/
- /.idea/
- 
flag: .bkstop
min_age: 10
size: 10M
# target: /tmp/backup.tar
~~~

## Restore

~~~
#!/bin/bash
PP="topsecret"
exec 2>&1
for F in $*
do
  echo "### showing ${F}"
  unxz <$F | gpg -d --passphrase "${PP}" --batch | tar tvf -
done
~~~
