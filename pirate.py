import requests
from bs4 import BeautifulSoup
import json
from urllib import parse
from datetime import datetime
import time


def construct_link(origin, destination):
    o = parse.urlparse(origin)

    if destination.startswith('http'):
        return destination
    elif destination.startswith('/'):
        return o.scheme + '://' + o.netloc + destination
    else:
        path = o.path.split('/')
        path = '/'.join(path[:-1])
        return o.scheme + '://' + o.netloc + path +'/' + destination


def parse_form(url, form):
    action = form.get('action')
    u = construct_link(url, action)

    data = {}

    for input in form.find_all('input'):
        if input.get('type') != 'submit':
            data[input.get('name')] = input.get('value')

    return u, data


def authenticate(target, kerberos, password, device, passcodes):
    # Create a session to persist cookies.
    s = requests.Session()
    r = s.get(target)

    # The system should redirect to IDP.
    if 'idp.mit.edu' not in r.url:
        return None

    # Post login information.
    url = 'https://idp.mit.edu/idp/Authn/UsernamePassword'
    data = {
        'j_username': kerberos,
        'j_password': password,
        'Submit': 'Login'
    }

    r = s.post(url, data=data)

    # Success occurs when DUO page appears.
    if 'Duo Authentication' not in r.text:
        return None

    # Search for required DUO data.
    duo = {}

    soup = BeautifulSoup(r.text, 'html.parser')
    for script in soup.find_all('script'):
        if 'Duo.init' in script.text:
            data = script.text.split()
            data = ''.join(data)
            data = data[9:-2]
            data = data.replace("'", "\"")
            duo = json.loads(data)

    # Exit if data not found.
    if duo.get('sig_request') is None or duo.get('host') is None:
        return None

    # Parse signature (from JavaScript).
    sig = duo['sig_request'].split('|')
    sig[2] = sig[2].replace(':APP', '')
    sig = '|'.join(sig[:3])

    # Perform some requests to get the tokens needed.
    payload = {
        'tx': sig,
        'parent': url
    }

    data = {
        'parent': url,
        'java_version': '',
        'flash_version': '22.0.0.209',
        'screen_resolution_width': 1920,
        'screen_resolution_height': 1080,
        'color_depth': 24
    }

    u = 'https://' + duo['host'] + '/frame/web/v1/auth'
    r = s.post(u, params=payload, data=data)

    start = r.url.find('sid=') + 4

    if start == -1:
        return None

    sid = parse.unquote(r.url[start:])
    u = 'https://' + duo['host'] + '/frame/prompt'
    u2 = 'https://' + duo['host'] + '/frame/status'

    # Apply DUO passcodes to login.
    success = False
    d = None

    for passcode in passcodes:
        data = {
            'sid': sid,
            'device': device,
            'factor': 'Passcode',
            'passcode': passcode,
            'out_of_date': ''
        }

        r = s.post(u, data=data)
        d = json.loads(r.text)
        txid = d['response']['txid']

        data = {
            'sid': sid,
            'txid': txid
        }

        r = s.post(u2, data=data)
        d = json.loads(r.text)

        if d['response']['status_code'] == 'allow':
            success = True
            break

    # Check for success:
    if not success:
        return None

    # Final parsing.
    data = {
        'sig_response': d['response']['cookie'] + ':APP|' + '|'.join(duo['sig_request'].split('|')[3:])
    }

    r = s.post(url, data=data)
    soup = BeautifulSoup(r.text, 'html.parser')

    form = soup.find('form')
    u, data = parse_form(r.url, form)

    # No form found. Exit early.
    if u is None or len(data) == 0:
        return None

    # Authenticate.
    s.post(u, data=data)

    # Return session.
    return s


def register(sections, s):
    list_url = 'https://edu-apps.mit.edu/mitpe/student/registration/sectionList'

    r = s.get(list_url)
    soup = BeautifulSoup(r.text, 'html.parser')

    # Go through table and select firs open section.
    table = soup.find('table')
    rows = table.find_all('tr')
    headers = [header.text.strip().lower() for header in rows[0].find_all('th')]

    # Locate desired header index.
    try:
        section_i = headers.index('section')
        openings_i = headers.index('available openings')
    except ValueError:
        print('Unable to find correct headers. Exiting.')
        return False

    dict = {}

    for row in rows[1:]:
        data = row.find_all('td')
        openings = int(data[openings_i].text.strip())
        section = data[section_i].text.strip()
        url = data[section_i].find('a')['href']

        dict[section] = (openings, url)

    for section in sections:
        sec = dict.get(section)

        if sec is None:
            print('No such section {}.'.format(section))
        elif sec[0] == 0:
            print('Section {} is already full.'.format(section))
        else:
            url = construct_link(r.url, sec[1])

            # Go to section.
            r = s.get(url)
            soup = BeautifulSoup(r.text, 'html.parser')

            # Submit form if possible.
            form = soup.find('form')
            button = form.find('button')
            b_text = button.text.lower()

            if 'register' in b_text:
                u, data = parse_form(url, form)
                r = s.post(u, data=data)
                soup = BeautifulSoup(r.text, 'html.parser')

                block = soup.find(id='successMsgBlock')

                if block is not None and 'success' in block.text.lower():
                    print('Successfully registered for {}!'.format(section))
                    return True
            else:
                print('Unable to register for {}.'.format(section))

    return False


def give_pirate(sections, credentials, begin):
    # Verify that time is correct.
    dt = datetime.fromtimestamp(begin)
    string = dt.strftime('%Y-%m-%d %H:%M %p')
    print('Registration begins at {} in your timezone.'.format(string))

    # Define URLs.
    auth_url = 'https://sisapp.mit.edu/mitpe/student'

    # Sleep until one minute before.
    print('Entering sleep cycle.')
    while time.time() < begin - 120:
        time.sleep(30)

    # Wake.
    print('Awoken. Trying to authenticate.')

    # Login beforehand.
    kerberos = credentials['kerberos']
    password = credentials['password']
    device = credentials['device']
    passcodes = credentials['passcodes']
    s = authenticate(auth_url, kerberos, password, device, passcodes)

    if s is None:
        print('Unable to authenticate. Exiting.')
        return
    else:
        print('Successfully authenticated.')

    # Be aggressive. I really want to be a pirate.
    i = 0
    while True:
        print('Trying to register: {}'.format(i))

        try:
            if register(sections, s):
                print('You are on your way to becoming a pirate!')
                break
        except Exception:
            print('Error while registering.')

        i += 1


credentials = {
    'kerberos': '',
    'password': '',
    'device': 'phone1',
    'passcodes': []
}

give_pirate(['PE.0608-3', 'PE.0608-6'], credentials, 1485954000)