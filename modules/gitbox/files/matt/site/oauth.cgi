#!/usr/bin/env python
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

# This is oauth.cgi - script for handling ASF and GitHub OAuth.

import hashlib, json, random, os, sys, time, subprocess
import cgi, sqlite3, hashlib, Cookie, urllib, urllib2, ConfigParser

# LDAP settings
CONFIG = ConfigParser.ConfigParser()
CONFIG.read("/x1/gitbox/matt/tools/grouper.cfg")

LDAP_URI = "ldaps://ldap-lb-us.apache.org:636"
LDAP_USER = CONFIG.get('ldap', 'user')
LDAP_PASSWORD = CONFIG.get('ldap', 'password')

# CGI
xform = cgi.FieldStorage();

""" Get a POST/GET value """
def getvalue(key):
    val = xform.getvalue(key)
    if val:
        return val
    else:
        return None
    
""" Get an account entry from the DB """
def getaccount(uid = None):
    cookies = Cookie.SimpleCookie(os.environ.get("HTTP_COOKIE", ""))
    if "matt" in cookies:
        cookie = cookies['matt']
        conn = sqlite3.connect('/x1/gitbox/db/gitbox.db')
        cursor = conn.cursor()
        cursor.execute("SELECT asfid,githubid,displayname FROM sessions WHERE cookie=?", (cookie,))
        row = cursor.fetchone()
        conn.close()
        if row:
            acc = {
                'asfid':  row[0],
                'github': row[1],
                'mfa':    0,
                'name':   row[2],
                'cookie': cookie,
            }
            return acc
    elif uid:
        conn = sqlite3.connect('/x1/gitbox/db/gitbox.db')
        cursor = conn.cursor()
        cursor.execute("SELECT asfid,githubid,displayname,cookie FROM sessions WHERE asfid=?", (uid,))
        row = cursor.fetchone()
        conn.close()
        if row:
            acc = {
                'asfid':  row[0],
                'github': row[1],
                'mfa':    0,
                'name':   row[2],
                'cookie': row[3],
            }
            return acc
    return None

""" Save/update an account """
def saveaccount(acc):
    conn = sqlite3.connect('/x1/gitbox/db/gitbox.db')
    cursor = conn.cursor()
    cursor.execute("SELECT asfid,githubid,displayname FROM sessions WHERE asfid=?", (aco['asfid'],))
    exists = cursor.fetchone()
    if exists:
        cursor.execute("UPDATE sessions SET cookie=?,githubid=?,displayname=?,mfa=? WHERE asfid=?", (acc['cookie'],acc['github'], acc['name'],acc['mfa'], acc['asfid'],))
    else:
        cursor.execute("INSERT INTO sessions (cookie,asfid,githubid,displayname,mfa) VALUES (?,?,?,?,?)" % (acc['asfid'], acc['github'], acc['name'], acc['mfa']))
    conn.commit()
    
""" Get LDAP groups a user belongs to """
def ldap_groups(uid):
    ldap.set_option(ldap.OPT_X_TLS_REQUIRE_CERT, ldap.OPT_X_TLS_NEVER)
    l = ldap.initialize(LDAP_URI)
    # this search for all objectClasses that user is in.
    # change this to suit your LDAP schema
    search_filter= "(&(cn=*)(memberUid=%s))" % uid
    try:
        groups = []
        LDAP_BASE = "ou=groups,dc=apache,dc=org"
        results = l.search_s(LDAP_BASE, ldap.SCOPE_SUBTREE, search_filter, ['cn',])
        for res in results:
            groups.append(res[1]['cn'][0]) # each res is a tuple: ('cn=full,ou=ldap,dc=uri', {'cn': ['tlpname']})
        return groups
    except Exception as err:
        pass
    return []

def main():    
    # Get some CGI vars
    load = getvalue("load")             # Fetch account info?
    logout = getvalue("logout")         # Log out of MATT?
    unauth = getvalue("unauth")         # Un-auth an account?
    redirect = getvalue("redirect")     # Redirect to OAuth provider
    code = getvalue("code")             # OAuth return code
    state = getvalue("state")           # OAuth return state
    key = getvalue("key")               # OAuth return key (github/asf)
    repos = getvalue("repos")           # List repos??
    
    # These vals need to be valid to pass OAuth later on
    valid = False
    js = None
    isASF = False
    doingOAuth = False
    
    # Load and return account info (including MFA status)
    if load and load == 'true':
        account = getaccount()
        if account:
            # MFA check
            if account['github']:
                gu = account['github']
                mfa = JSON.read(open("/x1/gitbox/matt/mfa.json", "r"))
                mfastatus = 0
                if gu in mfa['disabled']:
                    account['mfa'] = False
    
                if gu in mfa['enabled']:
                    account['mfa'] = True
    
            print("Status: 200 Okay\r\nContent-Type: application/json\r\n\r\n")
            print(json.dumps(account))
        else:
            print("Status: 200 Okay\r\nContent-Type: application/json\r\n\r\n{}")
    
    # Logout
    elif logout and logout == 'true':
        account = getaccount()
        if account:
            account['cookie'] = "--"
            saveaccount(account)
        print("Status: 302 Found\r\nLocation: /setup/\r\n\r\n")
    
    # Unauth from GitHub
    elif unauth and unauth == 'github':
        account = getaccount()
        if account:
            account['github'] = None
            saveaccount(account)
        print("Status: 302 Found\r\nLocation: /setup/\r\n\r\n")
    
    # OAuth provider redirect
    elif redirect:
        rootURL = "https://gitbox.apache.org/setup"
        state = hashlib.sha1(("%f-%s") % (time.time(), os.environ['REMOTE_ADDR'])).hexdigest()
        rurl = urllib.quote("%s/oauth.cgi?key=%s&state=%s" % (rootURL, redirect, state))
        if redirect == "apache":
            redir = "https://oauth.apache.org/?state=%s&redirect_uri=%s" % (state, rurl)
            print("Status: 302 Found\r\nLocation: %s\r\n\r\n" % redir)
        elif redirect == "github":
            f = open("/x1/gitbox/matt/tokens/appid.txt", "r").read()
            m = re.match(r"([a-f0-9]+)|([a-f0-9]+)", f)
            cid = m.group(1)
            csec = m.group(2)
            redir = "https://github.com/login/oauth/authorize?client_id=%s&scope=default&?state=%s&redirect_uri=%s" % (cid, state, rurl)
            print("Status: 302 Found\r\nLocation: %s\r\n\r\n" % redir)
    
    
    
    # GitHub OAuth callback
    elif code and state and key == 'github':
        doingOAuth = True
        # get id & secret from file
        f = open("/x1/gitbox/matt/tokens/appid.txt", "r").read()
        m = re.match(r"([a-f0-9]+)|([a-f0-9]+)", f)
        cid = m.group(1)
        csec = m.group(2)
        
        # Construct OAuth backend check POST data
        rargs = "%s&client_id=%s&client_secret=%s" % (os.environ.get("QUERY_STRING"), cid, csec)
        
        req = urllib2.Request("https://github.com/login/oauth/access_token", rargs)
        response = req.urlopen().read()
        token = re.match(r"(access_token=[a-f0-9]+)", response)
        # If we got an access token, fetch user data
        if token:
            req = urllib2.Request("https://api.github.com/user?%s" % token.group(1))
            response = urllib2.urlopen(req).read()
            js = json.loads(response)
            valid = True
        
    # ASF Oauth callback
    elif state and code and key == 'apache':
        doingOAuth = True
        isASF = True
        req = urllib2.Request("https://oauth.apache.org/token", os.environ.get("QUERY_STRING"))
        response = urllib2.urlopen(req).read()
        js = json.loads(response)
        valid = True
    
    # Did we get something useful from the backend?
    if valid and js:
        eml = js.get('email', None)
        fname = js.get('fullname', None)
        
        # update info
        updated = False
        ncookie = None
        if (eml and fname) or key == 'github':
            oaccount = None
            # If tying an ASF account, make a session in the DB (if not already there)
            if isASF and 'uid' in js:
                cid = js['uid']
                ncookie = hashlib.sha1("%f-%s" % (time.time(), os.environ.get("REMOTE_ADDR"))).hexdigest()
                # Does the user exist already?
                oaccount = getaccount(cid)
                
                # If not seen before, make a new session
                if not oaccount:
                    saveaccount({
                        'asfid': cid,
                        'name': js['fullname'],
                        'githubid': None,
                        'cookie': ncookie,
                        
                    })
                # Otherwise, update the old session with new cookie
                else:
                    oaccount['cookie'] = ncookie
                    saveaccount(oaccount)
                updated = true
            # GitHub linking
            elif key == 'github':
                oaccount = getaccount()
                if oaccount:
                    oaccount['githubid'] = js['login']
                    saveaccount(oaccount)
        
        # did stuff correctly!?
        if updated:
            print("Status: 302 Found\r\nLocation: /setup/\r\n")
            # New cookie set??
            if ncookie:
                print("Set-Cookie: matt=%s\r\n" % ncookie)
            print("\r\nMoved!")
        # didn't get email or name, bork!
        else:
            print("Status: 302 Found\r\nLocation: /setup/error.html\r\n\r\n")
    
    
    # Backend borked, let the user know
    elif doingOAuth:
        print("Status: 302 Found\r\nLocation: /setup/error.html\r\n\r\n")

    if repos:
        # Try to get cache if <1 hour old
        repolistfile = "/x1/gitbox/matt/repos.json"
        mtime = os.stat(repolistfile).st_mtime
        # File is too old, regenerate!
        repos = []
        if mtime < (time.time() - 3600):
            # get id & secret from file
            f = open("/x1/gitbox/matt/tokens/appid.txt", "r").read()
            m = re.match(r"([a-f0-9]+)|([a-f0-9]+)", f)
            cid = m.group(1)
            csec = m.group(2)
            for n in range(0,100):
                result = urllib2.urlopen("https://api.github.com/orgs/apache/repos?client_id=%s&client_secret=%s&page=%s" % (cid, csec, n)).read()
                js = json.loads(result)
                if json:
                    if len(json) == 0:
                        break
                    for repo in json:
                        repos.append(js[repo]['name'])
                else:
                    break
            # Save file
            json.dump(repos, open(repolistfile, "w"))
        else:
            repos = json.load(open(repolistfile))
            
        oaccount = getaccount()
        if oaccount:
            groups = ldap_groups(oaccount['asfid'])
            canAccess = {}
            print("Status: 200 Okay\r\nContent-Type: application/json\r\n\r\n")
            for group in groups:
                for repo in repos:
                    m = re.match(r"([^-]+)", repo)
                    g = m.group(1)
                    if g == group:
                        if not group in canAccess:
                            canAccess[group] = []
                        canAccess[group].append(repo)
            print(json.dumps(canAccess))

if __name__ == '__main__':
    main()
    