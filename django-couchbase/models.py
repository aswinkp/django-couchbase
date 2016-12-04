from __future__ import unicode_literals
from decimal import Decimal

from djangotoolbox.fields import ListField
from six import string_types
import logging
from django.utils import timezone, dateparse
from tastypie.serializers import Serializer

logger = logging.getLogger(__name__)

import couchbase
from django.db import models
from django.forms.models import model_to_dict
from django.http import HttpResponseNotFound
from django_cbtools import sync_gateway
from django.db import models
from django.utils import timezone
from django.db.models.fields.files import FileField
from couchbase.bucket import Bucket, NotFoundError, ValueResult
from django_extensions.db.fields import ShortUUIDField
from django.db.models.fields import DateTimeField, DecimalField
#from django_cbtools.models import CouchbaseModel, CouchbaseModelError
from django.conf import settings
from django_couchbase.fields import ModelReferenceField, PartialReferenceField
from djangotoolbox.fields import ListField, EmbeddedModelField, DictField

CHANNELS_FIELD_NAME = "channels"
DOC_TYPE_FIELD_NAME = "doc_type"

CHANNEL_PUBLIC = 'public'

# Create your models here.
class CouchbaseModelError(Exception):
    pass

class CBModel(models.Model):
    class Meta:
        abstract = True

    id_prefix = 'st'
    doc_type = None
    _serializer = Serializer()

    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.get_id() == other.get_id()

    def __init__(self, *args, **kwargs):
        self.channels = []
        self.id = None
        self.rev = None
        if hasattr(self, 'bucket'):
            self.db = self.get_bucket()
        if 'id_prefix' in kwargs:
            self.id_prefix = kwargs['id_prefix']
            del kwargs['id_prefix']

        if 'id' in kwargs:
            self.id = kwargs['id']
            del kwargs['id']

        clean_kwargs = self.__clean_kwargs(kwargs)
        # we never pass args because we never use them
        super(CBModel, self).__init__(**clean_kwargs)


        if len(args) == 1:
            v = args[0]
            if isinstance(v, ValueResult):
                self.load_list(v)
            if isinstance(v, string_types):
                self.load(v)

    def get_id(self):
        if self.is_new():
            pf = ShortUUIDField()
            self.id = self.id_prefix + '::' + pf.create_uuid()
        return self.id

    def get_bucket(self):
        return Bucket(''.join(['couchbase://', settings.CB_BUCKETS.get(self.bucket)]))

    def save(self, *args, **kwargs):
        self.updated = timezone.now()
        if not hasattr(self, 'created') or self.created is None:
            self.created = self.updated

        # save files
        for field in self._meta.fields:
            if isinstance(field, FileField):
                file_field = getattr(self, field.name)

                if not file_field._committed:
                    file_field.save(file_field.name, file_field, False)

        data_dict = self.to_dict()
        if self.is_new():
            self.db.add(self.get_id(), data_dict)
        else:
            self.db.set(self.get_id(), data_dict)


    # for saving
    def to_dict(self):
        d = model_to_dict(self)
        tastyjson = self._serializer.to_json(d)
        d = self._serializer.from_json(tastyjson)

        d[DOC_TYPE_FIELD_NAME] = self.get_doc_type()
        d['id'] = self.get_id()
        if 'cbnosync_ptr' in d: del d['cbnosync_ptr']
        if 'csrfmiddlewaretoken' in d: del d['csrfmiddlewaretoken']
        for field in self._meta.fields:
            if isinstance(field, DateTimeField):
                d[field.name] = self._string_from_date(field.name)
            if isinstance(field, ListField):
                if isinstance(field.item_field, EmbeddedModelField):
                    self.to_dict_nested_list(field.name, d)
                if isinstance(field.item_field, ModelReferenceField):
                    self.to_dict_reference_list(field.name, d)
            if isinstance(field, EmbeddedModelField):
                self.to_dict_nested(field.name, d)
            if isinstance(field, ModelReferenceField):
                self.to_dict_reference(field.name, d)
        return d

    def from_dict(self, dict_payload):
        for field in self._meta.fields:
            if field.name not in dict_payload:
                continue
            if isinstance(field, EmbeddedModelField):
                self.from_dict_nested(field.name, field.embedded_model, dict_payload)
                continue
            if isinstance(field, ListField):
                if isinstance(field.item_field, EmbeddedModelField):
                    self.from_dict_nested_list(field.name, field.item_field.embedded_model, dict_payload)
                continue
            if isinstance(field, DateTimeField):
                self._date_from_string(field.name, dict_payload.get(field.name))
            elif isinstance(field, DecimalField):
                self._decimal_from_string(field.name, dict_payload.get(field.name))
            elif field.name in dict_payload:
                setattr(self, field.name, dict_payload[field.name])
        if 'id' in dict_payload.keys():
            self.id = dict_payload['id']



    def from_row(self, row):
        self.from_dict(row.value)
        self.id = row.key

    def load(self, id):
        try:
            doc = self.db.get(id)
            self.from_row(doc)
        except:
            raise NotFoundError

    def load_list(self, doc):
        self.from_row(doc)

    def delete(self):
        try:
            for field in self._meta.fields:
                if isinstance(field, ModelReferenceField):
                    fld = getattr(self, field.name)
                    if isinstance(field, field.embedded_model):
                        fld.delete(self.id)
                    # TODO delete after load related and check on delete
                    # field.embedded_model.db.remove(getattr(self,field.name))
            self.db.remove(self.id)
        except NotFoundError:
            return HttpResponseNotFound

    def load_related(self,related_attr, related_klass):
        id = getattr(self, related_attr)
        return related_klass(id)

    def load_related_list(self,related_attr, related_klass):
        ids = getattr(self, related_attr)
        docs_arr = related_klass.db.get_multi(ids)
        objs = []
        for doc in docs_arr:
            value = docs_arr[doc]
            objs.append(related_klass(value))
        return objs

    def to_dict_nested(self, key, parent_dict):
        parent_dict[key] = getattr(self, key).to_dict()
        return parent_dict

    def to_dict_nested_list(self, key, parent_dict):
        parent_dict[key] = []
        for item in getattr(self, key):
            parent_dict[key].append(item.to_dict())
        return parent_dict

    def to_dict_reference(self, key, parent_dict):
        ref_obj = getattr(self,key)
        if ref_obj and not isinstance(ref_obj, string_types):
            ref_obj.save()
            parent_dict[key] = ref_obj.id
        return parent_dict

    def to_dict_reference_list(self, key, parent_dict):
        ref_objs = getattr(self, key)
        id_arr = []
        if isinstance(ref_objs, list) and len(ref_objs):
            for obj in ref_objs:
                if obj and not isinstance(obj, string_types):
                    obj.save()
                    id_arr.append(obj.id)
        parent_dict[key] =  id_arr
        return parent_dict

    def to_dict_partial_reference(self, key, parent_dict,links):
        ref_obj = getattr(self, key)
        if ref_obj and not isinstance(ref_obj, string_types):
            ref_obj.save()
            parent_dict[key] = ref_obj.id
            for key,value in links.iteritems():
                parent_dict[key] = getattr(ref_obj,value)
                pass
        return parent_dict

    def from_dict_nested(self, key, nested_klass, dict_payload):
        if key in dict_payload.keys():
            item = nested_klass()
            item.from_dict(dict_payload[key])
            nested_list = item
            setattr(self, key, nested_list)

    def from_dict_nested_list(self, key, nested_klass, dict_payload):
        setattr(self, key, [])
        nested_list = getattr(self, key)
        if key in dict_payload.keys():
            for d in dict_payload[key]:
                item = nested_klass()
                item.from_dict(d)
                nested_list.append(item)

    def append_to_references_list(self, key, value):
        v = getattr(self, key, [])

        if not isinstance(v, list):
            v = []

        if value not in v:
            v.append(value)

        setattr(self, key, v)

    def get_references_list(self, key):
        v = getattr(self, key, [])

        if not isinstance(v, list):
            v = []

        return v

    def delete_from_references_list(self, key, value):
        v = getattr(self, key, [])

        if not isinstance(v, list):
            v = []

        if value in v:
            v.remove(value)

        setattr(self, key, v)

    def is_new(self):
        return not hasattr(self, 'id') or not self.id

    def from_json(self, json_payload):
        d = self._serializer.from_json(json_payload)
        self.from_dict(d)

    def _date_from_string(self, field_name, val):
        try:
            setattr(self, field_name, dateparse.parse_datetime(val))
        except Exception as e:
            setattr(self, field_name, val)
            logger.warning('can not parse date (raw value used) %s: %s', field_name, e)

    def _string_from_date(self, field_name):
        try:
            return getattr(self, field_name).isoformat()
        except:
            return None

    def _decimal_from_string(self, field_name, val):
        try:
            setattr(self, field_name, Decimal(val))
        except Exception as e:
            setattr(self, field_name, val)
            logger.warning('can not parse decimal (raw value used) %s: %s', field_name, e)

    def to_json(self):
        d = self.to_dict()
        return self._serializer.to_json(d)

    def get_doc_type(self):
        if self.doc_type:
            return self.doc_type
        return self.__class__.__name__.lower()


    def __unicode__(self):
        return u'%s: %s' % (self.id, self.to_json())

    def __clean_kwargs(self, data):
        common = set.intersection(
            {f.name for f in self._meta.get_fields()},
            data.keys(),
        )
        return {fname: data[fname] for fname in common}


class CBNestedModel(CBModel):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        raise CouchbaseModelError('this object is not supposed to be saved, it is nested')

    def load(self, id):
        raise CouchbaseModelError('this object is not supposed to be loaded, it is nested')