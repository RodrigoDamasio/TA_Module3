| Python 2                          | Python 3                                   |
|-----------------------------------|--------------------------------------------|
| print "x", y                      | print("x", y)                              |
| except Error, e:                  | except Error as e:                         |
| d.iteritems() / itervalues()      | d.items() / d.values()                     |
| d.has_key(k)                      | k in d                                     |
| unicode(s) / basestring           | str(s) / str                               |
| long                              | int                                        |
| xrange                            | range                                      |
| raw_input                         | input                                      |
| urllib2.urlopen                   | urllib.request.urlopen (+ urllib.error)    |
| ConfigParser                      | configparser                               |
| StringIO / cPickle                | io.StringIO / pickle                       |
| eval(untrusted text)              | ast.literal_eval (and report it as a risk) |
