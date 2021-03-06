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

import json
import requests
from datetime import timedelta
from requests.auth import HTTPBasicAuth

from django.utils import timezone

# DamnedLies specific imports
from .config.damnedlies import resources as damnedlies_resources
from .config.damnedlies import resource_config_dict as damnedlies_config

# Transifex specific imports
from .config.transifex import resources as transifex_resources
from .config.transifex import resource_config_dict as transifex_config

# Zanata specific imports
from .config.zanata import resources as zanata_resources
from .config.zanata import resource_config_dict as zanata_config

# Weblate specific imports
from .config.weblate import resources as weblate_resources
from .config.weblate import resource_config_dict as weblate_config

from dashboard.constants import TRANSPLATFORM_ENGINES
from dashboard.models import CacheAPI


NO_CERT_VALIDATION = True


__all__ = ['ServiceConfig', 'RestHandle', 'RestClient']


class ServiceConfig(object):
    """
    REST communication service configuration
    """

    def _set_initials(self, service, resource, auth=None):
        """
        Sets initial params
        """

        master_config_dict = {
            TRANSPLATFORM_ENGINES[0]: {
                '_config_dict': damnedlies_config,
                '_middle_url': '',
                '_service': damnedlies_resources.get(resource),
                'http_auth': None
            },
            TRANSPLATFORM_ENGINES[1]: {
                '_config_dict': transifex_config,
                '_middle_url': "/api/2",
                '_service': transifex_resources.get(resource),
                'http_auth': HTTPBasicAuth(*auth) if auth else None
            },
            TRANSPLATFORM_ENGINES[2]: {
                '_config_dict': zanata_config,
                '_middle_url': '/rest',
                '_service': zanata_resources.get(resource),
                'http_auth': None
            },
            TRANSPLATFORM_ENGINES[3]: {
                '_config_dict': weblate_config,
                '_middle_url': '/api',
                '_service': weblate_resources.get(resource),
                'http_auth': None
            },
        }
        required_config = master_config_dict.get(service).copy()
        for attrib, value in required_config.items():
            setattr(self, str(attrib), value)

    def __init__(self, service, resource, auth=None):
        """
        entry point
        """
        self._set_initials(service, resource, auth)
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
            # filter kwargs
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


def cache_api_response():
    """
    decorator to check db for API response
    :return: response dict
    """
    def response_decorator(caller):
        def inner_decorator(obj, base_url, resource, *args, **kwargs):
            try:
                fields = ['expiry', 'response_raw']
                filter_params = {
                    'base_url': base_url,
                    'resource': resource,
                }
                cache = CacheAPI.objects.only(*fields).filter(**filter_params).first() or []
            except Exception as e:
                # log error
                pass
            else:
                if timezone.now() > cache[0]:
                    return cache[1]
            return caller(obj, base_url, resource, *args, **kwargs)
        return inner_decorator
    return response_decorator


class RestClient(object):

    """
    REST Client for all Managers
    """

    SAVE_RESPONSE = True
    EXPIRY_MIN = 60

    def __init__(self, service):

        self.service = service
        self.disable_ssl_certificate_validation = NO_CERT_VALIDATION

    def disable_ssl_cert_validation(self):
        self.disable_ssl_certificate_validation = True

    def _save_response(self, req_base_url, req_resource, resp_content, resp_content_json,
                       *req_args, **req_kwargs):
        """
        Save API responses in db
        """
        cache_params = {}
        match_params = {
            'base_url': req_base_url,
            'resource': req_resource,
        }
        cache_params.update(match_params)
        cache_params['request_args'] = req_args
        cache_params['request_kwargs'] = str(req_kwargs)
        cache_params['response_content'] = resp_content
        cache_params['response_content_json_str'] = json.dumps(resp_content_json)
        cache_params['expiry'] = timezone.now() + timedelta(minutes=self.EXPIRY_MIN)
        try:
            CacheAPI.objects.update_or_create(
                base_url=req_base_url, resource=req_resource, defaults=cache_params
            )
        except Exception as e:
            # log error
            pass

    def _return_cached_response(self, base_url, resource):
        """
        Check cached response in db
        :param base_url:
        :param resource:
        :return:
        """
        try:
            fields = ['expiry', 'response_content', 'response_content_json_str']
            filter_params = {
                'base_url': base_url,
                'resource': resource,
            }
            cache = CacheAPI.objects.only(*fields).filter(**filter_params).first()
        except Exception as e:
            # log error
            pass
        else:
            if cache:
                if cache.expiry > timezone.now():
                    return cache.response_content, cache.response_content_json
        return False, False

    def process_request(self, base_url, resource, *args, **kwargs):
        """
        Process REST Request
        :param base_url: str
        :param resource: str
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
            if self.service == TRANSPLATFORM_ENGINES[1]:
                auth_tuple = (kwargs['auth_user'], kwargs['auth_token'])
            elif self.service == TRANSPLATFORM_ENGINES[2]:
                headers['X-Auth-User'] = kwargs['auth_user']
                headers['X-Auth-Token'] = kwargs['auth_token']
        # set headers
        service_details = ServiceConfig(self.service, resource, auth=auth_tuple)
        if hasattr(service_details, 'response_media_type') and service_details.response_media_type:
            headers['Accept'] = service_details.response_media_type
        if hasattr(service_details, 'request_media_type') and service_details.request_media_type:
            headers['Content-Type'] = service_details.request_media_type
        # set resource
        resource = (
            service_details.resource.format(**dict(zip(service_details.path_params or [], args)))
            if args else service_details.resource
        )
        if isinstance(extension, bool):   # extension should be boolean
            ext = "&".join(service_details.query_params)
            resource = resource + "?" + ext
        elif isinstance(extension, str):
            resource = resource + "?" + extension
        # Lets check with cache
        c_content, c_json_content = self._return_cached_response(base_url, resource)
        if c_content:
            return {'content': c_content, 'json_content': c_json_content}
        # initiate service call
        rest_handle = RestHandle(
            base_url, resource, service_details.http_method, auth=service_details.auth,
            body=body, headers=headers, connection_type=None, cache=None,
            disable_ssl_certificate_validation=self.disable_ssl_certificate_validation
        )
        api_response_dict = rest_handle.get_response_dict()
        if self.SAVE_RESPONSE:
            self._save_response(base_url, resource, api_response_dict['content'],
                                api_response_dict['json_content'], *args, **kwargs)
        return api_response_dict
