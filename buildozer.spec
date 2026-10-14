[app]

title = Warehouse App

package.name = warehouseapp

package.domain = org.example

source.dir = .

source.include_exts = py,kv,png,ttf,db

version = 0.1

requirements = python3,kivy,sqlite3

orientation = portrait

android.permissions = INTERNET,WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE

android.api = 31

android.minapi = 21

android.ndk = 25.2.9519653

source.filenames = main.py

bin_dir = bin

[buildozer]

log_level = 2

clean = True
