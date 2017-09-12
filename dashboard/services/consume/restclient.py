# Copyright 2016 Red Hat, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import requests
from requests.auth import HTTPBasicAuth


# Transifex specific imports
from .config.transifex import services as transifex_services
from .config.transifex import resource_config_dict as transifex_resources

# Zanata specific imports
from .config.zanata import services as zanata_services
from .config.zanata import resource_config_dict as zanata_resources

# DamnedLies specific imports
from .config.damnedlies import services as damnedlies_services
from .config.damnedlies import resource_config_dict as damnedlies_resources

from dashboard.constants import TRANSPLATFORM_ENGINES


NO_CERT_VALIDATION = True


__all__ = ['ServiceConfig', 'RestHandle', 'RestClient']


class ServiceConfig(object):
    """
    transplatform service configuration
    """
    def __init__(self, engine, service, auth=None):
        """
        entry point
        """
        if engine == TRANSPLATFORM_ENGINES[0]:
            self._config_dict = transifex_resources
            self._middle_url = '/api/2'
            self._service = transifex_services[service]
            self.http_auth = HTTPBasicAuth(*auth)
        if engine == TRANSPLATFORM_ENGINES[1]:
            self._config_dict = zanata_resources
            self._middle_url = '/rest'
            self._service = zanata_services[service]
            self.http_auth = None
        if engine == TRANSPLATFORM_ENGINES[2]:
            self._config_dict = damnedlies_resources
            self._middle_url = ''
            self._service = damnedlies_services[service]
            self.http_auth = None

        for attrib, value in (self._config_dict[self._service.rest_resource]
                              [self._service.mount_point][self._service.http_method].items()):
            setattr(self, str(attrib), value)

    @property
    def resource_group(self):
        return self._service.rest_resource

    @property
    def mount_points(self):
        return list(self._config_dict[self._service.rest_resource].keys())

    @property
    def resource(self):
        return self._middle_url + self._service.mount_point

    @property
    def mount_point(self):
        return self._service.mount_point

    @property
    def http_method(self):
        return self._service.http_method

    @property
    def auth(self):
        return self.http_auth


class RestHandle(object):
    """
    handle for REST communication
    """
    def __init__(self, *args, **kwargs):
        """
        RestHandle constructor
        :param args: base="http://localhost", uri="/zanata", method="GET"
        :param kwargs: body=None, headers=None, redirections=DEFAULT_MAX_REDIRECTS, connection_type=None,
                        cache=".cache", ext="?lang=hi"
        """
        if len([arg for arg in args if arg]) != 3:
            raise Exception('Insufficient args.')
        self.base_url, self.uri, self.method = args

        for attrib, value in kwargs.items():
            if value:
                setattr(self, str(attrib), value)

    def _get_url(self):
        if self.base_url[-1:] == '/':
            self.base_url = self.base_url[:-1]
        return '%s%s%s' % (self.base_url, self.uri, getattr(self, 'ext')) \
            if hasattr(self, 'ext') else '%s%s' % (self.base_url, self.uri)

    def _call_request(self, uri, http_method, **kwargs):
        # TS consumes read APIs only

        if http_method != 'GET':
            return
        try:
            # filter kwrags
            kwargs.pop('body')
            kwargs.pop('connection_type')
            # send request
            rest_response = requests.get(uri, **kwargs)
            return rest_response
        except requests.ConnectionError:
            # event of a network problem (e.g. DNS failure, refused connection, etc)
            return False
        except requests.HTTPError:
            # the HTTP request returned an unsuccessful status code
            # Need to check its an 404, 503, 500, 403 etc.

            # todo
            # error handling on the basis on status code

            return False
        except requests.Timeout:
            # requests Times out
            return False
        except requests.TooManyRedirects:
            # exceeds the configured number of maximum redirections
            return False
        except Exception:
            # requests.exceptions.RequestException.
            return False

    def get_response_dict(self):
        request_args = ('body', 'headers', 'connection_type', 'auth')
        args_dict = dict(zip(
            request_args, [getattr(self, arg, None) for arg in request_args]
        ))

        if self.disable_ssl_certificate_validation:
            args_dict.update(dict(verify=False))

        response = self._call_request(self._get_url(), self.method, **args_dict)
        response_dict = {}
        if response and response.ok:
            try:
                response_dict.update(dict(json_content=response.json()))
            except ValueError:
                response_dict.update(dict(json_content={}))
            response_dict.update(dict(status_code=response.status_code))
            response_dict.update(dict(headers=response.headers))
            response_dict.update(dict(time_delta=response.elapsed))
            response_dict.update(dict(content=response.text))
            response_dict.update(dict(url=response.url))
            response_dict.update(dict(raw=response))
        return response_dict


class RestClient(object):

    """
    REST Client for all Managers
    """

    def __init__(self, engine, base_url):

        self.engine = engine
        self.base_url = base_url
        self.disable_ssl_certificate_validation = NO_CERT_VALIDATION

    def disable_ssl_cert_validation(self):
        self.disable_ssl_certificate_validation = True

    def process_request(self, service_name, *args, **kwargs):
        """
        Process REST Request
        :param service_name: str
        :param args: tuple
        :param kwargs: dict
        :return: dict
        """
        headers = kwargs['headers'] if 'headers' in kwargs else {}
        body = kwargs['body'] if 'body' in kwargs else None
        extension = kwargs.get('ext')
        # set auth
        auth_tuple = None
        if kwargs.get('auth_user') and kwargs.get('auth_token'):
            if self.engine == TRANSPLATFORM_ENGINES[0]:
                auth_tuple = (kwargs['auth_user'], kwargs['auth_token'])
            elif self.engine == TRANSPLATFORM_ENGINES[1]:
                headers['X-Auth-User'] = kwargs['auth_user']
                headers['X-Auth-Token'] = kwargs['auth_token']
        # set headers
        service_details = ServiceConfig(self.engine, service_name, auth=auth_tuple)
        if hasattr(service_details, 'response_media_type') and service_details.response_media_type:
            headers['Accept'] = service_details.response_media_type
        if hasattr(service_details, 'request_media_type') and service_details.request_media_type:
            headers['Content-Type'] = service_details.request_media_type
        # set resource
        resource = (
            service_details.resource.format(**dict(zip(service_details.path_params, args)))
            if args else service_details.resource
        )
        if extension:   # extension should always be boolean
            ext = "&".join(service_details.query_params)
            resource = resource + "?" + ext
        # initiate service call
        rest_handle = RestHandle(
            self.base_url, resource, service_details.http_method, auth=service_details.auth,
            body=body, headers=headers, connection_type=None, cache=None,
            disable_ssl_certificate_validation=self.disable_ssl_certificate_validation
        )
        return rest_handle.get_response_dict()