================
django-couchbase
================

This package is aimed at developing the ORM for the couchbase - the next generation NoSQL database.


Dependencies
------------

Make sure you install the below dependencies::

    couchbase==2.0.9
    shortuuid==0.4.3
    six==1.10.0
    django-extensions==1.6.7
    django-tastypie==0.13.3

Quick Install
-------------

Install django-couchbase package::

    pip install django-couchbase

The following configuration settings are used for the package (you can use the set below for the fast installation)::


    CB_BUCKETS = {
        "MAIN_BUCKET" : '127.0.0.1/default'
    }

Add ``django_couchbase`` to ``INSTALLED_APPS``::

    INSTALLED_APPS = (
        # ...
        'django_couchbase',
    )

