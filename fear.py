#! /usr/bin/env python

"""
    FEAR - FEtching ARticles using Google Scholar

    Copyright 2014 Ali Parsai, All rights reserved.
    includes code from scholar.py Copyright 2010-2013 Christian Kreibich.

    contact me at ali@parsai.net if you have any suggestions.


    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""



import difflib
from pybtex.database.input import bibtex

import optparse
import sys
import string
import re

try:
    # Try importing for Python 3
    # pylint: disable-msg=F0401
    # pylint: disable-msg=E0611
    from urllib.request import HTTPCookieProcessor, Request, build_opener
    from urllib.parse import quote, urlretrieve
    from http.cookiejar import CookieJar
except ImportError:
    # Fallback for Python 2
    from urllib2 import Request, build_opener, HTTPCookieProcessor
    from urllib import quote, urlretrieve
    from cookielib import CookieJar

# Import BeautifulSoup -- try 4 first, fall back to older
try:
    from bs4 import BeautifulSoup
except ImportError:
    try:
        from BeautifulSoup import BeautifulSoup
    except:
        print('We need BeautifulSoup, sorry...')
        sys.exit(1)

# Support unicode in both Python 2 and 3. In Python 3, unicode is str.
if sys.version_info[0] == 3:
    unicode = str # pylint: disable-msg=W0622
    encode = lambda s: s # pylint: disable-msg=C0103
else:
    encode = lambda s: s.encode('utf-8') # pylint: disable-msg=C0103


class Article(object):
    """
    A class representing articles listed on Google Scholar.  The class
    provides basic dictionary-like behavior.
    """
    def __init__(self):
        self.attrs = {'title':         [None, 'Title',          0],
                      'url':           [None, 'URL',            1],
                      'num_citations': [0,    'Citations',      2],
                      'num_versions':  [0,    'Versions',       3],
                      'url_citations': [None, 'Citations list', 4],
                      'url_versions':  [None, 'Versions list',  5],
                      'year':          [None, 'Year',           6],
                      'url_pdf':       [None, 'PDF file',       7]}


    def __getitem__(self, key):
        if key in self.attrs:
            return self.attrs[key][0]
        return None

    def __len__(self):
        return len(self.attrs)

    def __setitem__(self, key, item):
        if key in self.attrs:
            self.attrs[key][0] = item
        else:
            self.attrs[key] = [item, key, len(self.attrs)]

    def __delitem__(self, key):
        if key in self.attrs:
            del self.attrs[key]

    def as_txt(self):
        # Get items sorted in specified order:
        items = sorted(list(self.attrs.values()), key=lambda item: item[2])
        # Find largest label length:
        max_label_len = max([len(str(item[1])) for item in items])
        fmt = '%%%ds %%s' % max_label_len
        return '\n'.join([fmt % (item[1], item[0]) for item in items])

    def as_csv(self, header=False, sep='|'):
        # Get keys sorted in specified order:
        keys = [pair[0] for pair in \
                sorted([(key, val[2]) for key, val in list(self.attrs.items())],
                       key=lambda pair: pair[1])]
        res = []
        if header:
            res.append(sep.join(keys))
        res.append(sep.join([unicode(self.attrs[key][0]) for key in keys]))
        return '\n'.join(res)


class ScholarParser(object):
    """
    ScholarParser can parse HTML document strings obtained from Google
    Scholar. It invokes the handle_article() callback on each article
    that was parsed successfully.
    """
    SCHOLAR_SITE = 'http://scholar.google.com'

    def __init__(self, site=None):
        self.soup = None
        self.article = None
        self.site = site or self.SCHOLAR_SITE
        self.year_re = re.compile(r'\b(?:20|19)\d{2}\b')

    def handle_article(self, art):
        """
        In this base class, the callback does nothing.
        """

    def parse(self, html):
        """
        This method initiates parsing of HTML content.
        """
        self.soup = BeautifulSoup(html)
        for div in self.soup.findAll(ScholarParser._tag_checker):
            self._parse_article(div)

    def _parse_article(self, div):
        self.article = Article()

        for tag in div:
            if not hasattr(tag, 'name'):
                continue

            if tag.name == 'div' and self._tag_has_class(tag, 'gs_rt') and \
                    tag.h3 and tag.h3.a:
                self.article['title'] = ''.join(tag.h3.a.findAll(text=True))
                self.article['url'] = self._path2url(tag.h3.a['href'])

            if tag.name == 'font':
                for tag2 in tag:
                    if not hasattr(tag2, 'name'):
                        continue
                    if tag2.name == 'span' and self._tag_has_class(tag2, 'gs_fl'):
                        self._parse_links(tag2)

        if self.article['title']:
            self.handle_article(self.article)

    def _parse_links(self, span):
        for tag in span:
            if not hasattr(tag, 'name'):
                continue
            if tag.name != 'a' or tag.get('href') is None:
                continue

            if tag.get('href').startswith('/scholar?cites'):
                if hasattr(tag, 'string') and tag.string.startswith('Cited by'):
                    self.article['num_citations'] = \
                        self._as_int(tag.string.split()[-1])
                self.article['url_citations'] = self._path2url(tag.get('href'))

            if tag.get('href').startswith('/scholar?cluster'):
                if hasattr(tag, 'string') and tag.string.startswith('All '):
                    self.article['num_versions'] = \
                        self._as_int(tag.string.split()[1])
                self.article['url_versions'] = self._path2url(tag.get('href'))

            if tag.get('href').lower().find('.pdf') > 0:
                self.article['url_pdf'] = self._path2url(tag.get('href'))



    @staticmethod
    def _tag_has_class(tag, klass):
        """
        This predicate function checks whether a BeatifulSoup Tag instance
        has a class attribute.
        """
        res = tag.get('class') or []
        if type(res) != list:
            # BeautifulSoup 3 can return e.g. 'gs_md_wp gs_ttss',
            # so split -- conveniently produces a list in any case
            res = res.split()
        return klass in res

    @staticmethod
    def _tag_checker(tag):
        return tag.name == 'div' and ScholarParser._tag_has_class(tag, 'gs_r')

    @staticmethod
    def _as_int(obj):
        try:
            return int(obj)
        except ValueError:
            return None

    def _path2url(self, path):
        if path.startswith('http://'):
            return path
        if not path.startswith('/'):
            path = '/' + path
        return self.site + path



class ScholarParser120726(ScholarParser):
    """
    This class reflects update to the Scholar results page layout that
    Google made 07/26/12.
    """
    def _parse_article(self, div):
        self.article = Article()

        for tag in div:
            if not hasattr(tag, 'name'):
                continue
            if str(tag).lower().find('.pdf'):
                if tag.find('div', {'class': 'gs_ttss'}):
                    self._parse_links(tag.find('div', {'class': 'gs_ttss'}))

            if tag.name == 'div' and self._tag_has_class(tag, 'gs_ri'):
                if tag.a:
                    self.article['title'] = ''.join(tag.a.findAll(text=True))
                    self.article['url'] = self._path2url(tag.a['href'])

                if tag.find('div', {'class': 'gs_a'}):
                    year = self.year_re.findall(tag.find('div', {'class': 'gs_a'}).text)
                    self.article['year'] = year[0] if len(year) > 0 else None

                if tag.find('div', {'class': 'gs_fl'}):
                    self._parse_links(tag.find('div', {'class': 'gs_fl'}))

        if self.article['title']:
            self.handle_article(self.article)


class ScholarQuerier(object):
    """
    ScholarQuerier instances can conduct a search on Google Scholar
    with subsequent parsing of the resulting HTML content.  The
    articles found are collected in the articles member, a list of
    Article instances.
    """
    SCHOLAR_URL = 'http://scholar.google.com/scholar?hl=en&q=%(query)s+author:%(author)s&btnG=Search&as_subj=eng&as_sdt=1,5&as_ylo=&as_vis=0'
    NOAUTH_URL = 'http://scholar.google.com/scholar?hl=en&q=%(query)s&btnG=Search&as_subj=eng&as_std=1,5&as_ylo=&as_vis=0'

    # Older URLs:
    # http://scholar.google.com/scholar?q=%s&hl=en&btnG=Search&as_sdt=2001&as_sdtp=on

    USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/32.0.1664.3 Safari/537.36'

    class Parser(ScholarParser120726):
        def __init__(self, querier):
            ScholarParser120726.__init__(self)
            self.querier = querier

        def handle_article(self, art):
            self.querier.add_article(art)

    def __init__(self, author='', scholar_url=None, count=0):
        self.articles = []
        self.author = author
        # Clip to 100, as Google doesn't support more anyway
        self.count = min(count, 100)

        if author == '':
            self.scholar_url = self.NOAUTH_URL
        else:
            self.scholar_url = scholar_url or self.SCHOLAR_URL

        if self.count != 0:
            self.scholar_url += '&num=%d' % self.count

        self.cjar = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.cjar))

    def query(self, search):
        """
        This method initiates a query with subsequent parsing of the
        response.
        """
        self.clear_articles()
        url = self.scholar_url % {'query': quote(encode(search)), 'author': quote(self.author)}
        req = Request(url=url, headers={'User-Agent': self.USER_AGENT})
        hdl = self.opener.open(req)
        html = hdl.read()
        self.parse(html)

    def parse(self, html):
        """
        This method allows parsing of existing HTML content.
        """
        parser = self.Parser(self)
        parser.parse(html)

    def add_article(self, art):
        self.articles.append(art)

    def clear_articles(self):
        """Clears any existing articles stored from previous queries."""
        self.articles = []

def getArticles(query):
    querier = ScholarQuerier(author='', count=1)
    querier.query(query)
    articles = querier.articles

    return articles[0]




def main():
    usage = """fear.py <bibtex file>
FEAR - FEtching ARticles using Google Scholar

Copyright 2014 Ali Parsai, All rights reserved.
includes code from scholar.py Copyright 2010-2013 Christian Kreibich

Example: fear.py file.bib"""

    fmt = optparse.IndentedHelpFormatter(max_help_position=50, width=100)
    parser = optparse.OptionParser(usage=usage, formatter=fmt)
    options, args = parser.parse_args()

    # Show help if we have neither keyword search nor author name
    if len(args) == 0:
        parser.print_help()
        return 1

    valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
    bibtexfilename = ' '.join(args)
    bibparser = bibtex.Parser()
    bibdata = bibparser.parse_file(bibtexfilename)

    for bib_id in bibdata.entries:
        b = bibdata.entries[bib_id].fields
        try:
            print "---------------------------------------------------------------"
            print "processing " + b["title"]
            article = getArticles(b["title"])
            confidence = difflib.SequenceMatcher(None, article.attrs["title"][0], b["title"]).ratio()
            if confidence > 0.80:
                print "match found! confidence: " + str(confidence)
                if article.attrs["url_pdf"][0] is None:
                    print "no pdf link found."
                    continue
                else:
                    outputfilename = b["title"]
                    outputfilename = ''.join(c for c in outputfilename if c in valid_chars)+".pdf"
                    urlretrieve(article.attrs["url_pdf"][0], outputfilename)
                    print "downloaded " + outputfilename
            print "---------------------------------------------------------------"
        except(KeyError):
            continue




if __name__ == "__main__":
    sys.exit(main())

