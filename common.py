#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging
import urllib
import urllib2

## Initialize module logging
formatter = logging.Formatter(u'%(message)s')
logger = logging.getLogger(u'tomato')
logger.setLevel(logging.DEBUG)
if hasattr(logger, 'handlers') and not logger.handlers:
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(u'%(message)s'))
    logger.addHandler(ch)
    fh = logging.FileHandler(u'tomato-cmd.log', encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
                    u'%(asctime)s\t%(levelname)s\t%(message)s'))
    logger.addHandler(fh)

class UrlParser:
    
    def __init__(self, url):
        self.url = url
        self.schema, url = urllib2.splittype(url)
        host, path = urllib2.splithost(url)
        userpass, host = urllib2.splituser(host)
        if userpass:
            self.user, self.password = urllib2.splitpasswd(userpass)
        path, self.querystring = urllib.splitquery(path)
        self.query = self.querystring and self.querystring.split('&') or []
        #urllib.splitquery(url)
        self.host, self.port = urllib2.splitport(host)
        path, self.tag = urllib2.splittag(path)
        self.path = path.strip('/')
    
    def path_parts(self):
        return self.path.split('/')
