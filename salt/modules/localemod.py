# -*- coding: utf-8 -*-
'''
Module for managing locales on POSIX-like systems.
'''
from __future__ import absolute_import

# Import python libs
import logging
import re
import os

# Import salt libs
import salt.utils
import salt.ext.six as six
import salt.utils.decorators as decorators

log = logging.getLogger(__name__)

# Define the module's virtual name
__virtualname__ = 'locale'


def __virtual__():
    '''
    Only work on POSIX-like systems
    '''
    if salt.utils.is_windows():
        return False
    return __virtualname__


def _parse_localectl():
    '''
    Get the 'System Locale' parameters from localectl
    '''
    ret = {}
    for line in __salt__['cmd.run']('localectl').splitlines():
        cols = [x.strip() for x in line.split(':', 1)]
        if len(cols) > 1:
            cur_param = cols.pop(0)
        if cur_param == 'System Locale':
            try:
                key, val = re.match('^([A-Z_]+)=(.*)$', cols[0]).groups()
            except AttributeError:
                log.error('Odd locale parameter "{0}" detected in localectl '
                          'output. This should not happen. localectl should '
                          'catch this. You should probably investigate what '
                          'caused this.'.format(cols[0]))
            else:
                ret[key] = val.replace('"', '')
    return ret


def _localectl_get():
    '''
    Use systemd's localectl command to get the current locale
    '''
    return _parse_localectl().get('LANG', '')


def _localectl_set(locale=''):
    '''
    Use systemd's localectl command to set the LANG locale parameter, making
    sure not to trample on other params that have been set.
    '''
    locale_params = _parse_localectl()
    locale_params['LANG'] = str(locale)
    args = ' '.join(['{0}="{1}"'.format(k, v)
                     for k, v in six.iteritems(locale_params)])
    cmd = 'localectl set-locale {0}'.format(args)
    return __salt__['cmd.retcode'](cmd, python_shell=False) == 0


def list_avail():
    '''
    Lists available (compiled) locales

    CLI Example:

    .. code-block:: bash

        salt '*' locale.list_avail
    '''
    cmd = 'locale -a'
    out = __salt__['cmd.run'](cmd).split('\n')
    return out


def get_locale():
    '''
    Get the current system locale

    CLI Example:

    .. code-block:: bash

        salt '*' locale.get_locale
    '''
    cmd = ''
    if 'Arch' in __grains__['os_family']:
        return _localectl_get()
    elif 'RedHat' in __grains__['os_family']:
        cmd = 'grep "^LANG=" /etc/sysconfig/i18n'
    elif 'Debian' in __grains__['os_family']:
        cmd = 'grep "^LANG=" /etc/default/locale'
    elif 'Gentoo' in __grains__['os_family']:
        cmd = 'eselect --brief locale show'
        return __salt__['cmd.run'](cmd).strip()

    try:
        return __salt__['cmd.run'](cmd).split('=')[1].replace('"', '')
    except IndexError:
        return ''


def set_locale(locale):
    '''
    Sets the current system locale

    CLI Example:

    .. code-block:: bash

        salt '*' locale.set_locale 'en_US.UTF-8'
    '''
    if 'Arch' in __grains__['os_family']:
        return _localectl_set(locale)
    elif 'RedHat' in __grains__['os_family']:
        __salt__['file.sed'](
            '/etc/sysconfig/i18n', '^LANG=.*', 'LANG="{0}"'.format(locale)
        )
        if __salt__['cmd.retcode']('grep "^LANG=" /etc/sysconfig/i18n') != 0:
            __salt__['file.append']('/etc/sysconfig/i18n',
                                    '"\nLANG={0}"'.format(locale))
    elif 'Debian' in __grains__['os_family']:
        __salt__['file.sed'](
            '/etc/default/locale', '^LANG=.*', 'LANG="{0}"'.format(locale)
        )
        if __salt__['cmd.retcode']('grep "^LANG=" /etc/default/locale') != 0:
            __salt__['file.append']('/etc/default/locale',
                                    '"\nLANG={0}"'.format(locale))
    elif 'Gentoo' in __grains__['os_family']:
        cmd = 'eselect --brief locale set {0}'.format(locale)
        return __salt__['cmd.retcode'](cmd, python_shell=False) == 0

    return True


def _normalize_locale(locale):
    # depending on the environment, the provided locale will also contain a charmap
    # (e.g. 'en_US.UTF-8 UTF-8' instead of only the locale 'en_US.UTF-8')
    # drop the charmap
    locale = locale.split()[0]

    lang_encoding = locale.split('.')
    lang_split = lang_encoding[0].split('_')
    if len(lang_split) > 1:
        lang_split[1] = lang_split[1].upper()
    lang_encoding[0] = '_'.join(lang_split)
    if len(lang_encoding) > 1:
        if len(lang_split) > 1:
            lang_encoding[1] = lang_encoding[1].lower().replace('-', '')
    return '.'.join(lang_encoding)


def avail(locale):
    '''
    Check if a locale is available.

    .. versionadded:: 2014.7.0

    CLI Example:

    .. code-block:: bash

        salt '*' locale.avail 'en_US.UTF-8'
    '''
    try:
        normalized_locale = _normalize_locale(locale)
    except IndexError:
        log.error('Unable to validate locale "{0}"'.format(locale))
        return False
    avail_locales = __salt__['locale.list_avail']()
    locale_exists = next((True for x in avail_locales
       if _normalize_locale(x.strip()) == normalized_locale), False)
    return locale_exists


@decorators.which('locale-gen')
def gen_locale(locale, charmap=None):
    '''
    Generate a locale.

    .. versionadded:: 2014.7.0

    :param locale: Any locale listed in /usr/share/i18n/locales or
        /usr/share/i18n/SUPPORTED for debian and gentoo based distros

    :param charmap: debian and gentoo based systems require the charmap to be
        specified independently of the locale.

    CLI Example:

    .. code-block:: bash

        salt '*' locale.gen_locale en_US.UTF-8
        salt '*' locale.gen_locale en_US.UTF-8 UTF-8  # debian and gentoo only
    '''
    on_debian = __grains__.get('os') == 'Debian'
    on_gentoo = __grains__.get('os_family') == 'Gentoo'

    if on_debian or on_gentoo:
        if not charmap:
            log.error('On debian and gentoo systems you must provide a charmap')
            return False

        search = '/usr/share/i18n/SUPPORTED'
        locale_format = '{0} {1}'.format(locale, charmap)
        valid = __salt__['file.search'](search, '^{0}$'.format(locale_format))
    else:
        search = '/usr/share/i18n/locales'
        locale_format = locale
        valid = locale_format in os.listdir(search)

    if not valid:
        log.error('The provided locale "{0}" is not found in {1}'.format(locale, search))
        return False

    if on_debian or on_gentoo:
        __salt__['file.replace'](
            '/etc/locale.gen',
            r'^#\s*{0}$'.format(locale_format),
            '{0}'.format(locale_format),
            append_if_not_found=True
        )
    elif __grains__.get('os') == 'Ubuntu':
        __salt__['file.touch'](
            '/var/lib/locales/supported.d/{0}'.format(locale.split('_')[0])
        )
        __salt__['file.append'](
            '/var/lib/locales/supported.d/{0}'.format(locale.split('_')[0]),
            '{0} {1}'.format(locale, locale.split('.')[1])
        )
        return __salt__['cmd.retcode'](
            'locale-gen'
        )

    cmd = ['locale-gen']
    if on_gentoo:
        cmd.append('--generate')
    cmd.append(locale_format)

    return __salt__['cmd.retcode'](cmd, python_shell=False)
