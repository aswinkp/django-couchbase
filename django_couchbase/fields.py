from django.db import models


class ModelReferenceField(models.CharField):

    def __init__(self, embedded_model=None, *args, **kwargs):
        self.embedded_model = embedded_model
        kwargs.setdefault('default', None)
        super(ModelReferenceField, self).__init__(*args, **kwargs)


    def get_internal_type(self):
        return 'ModelReferenceField'

class PartialReferenceField(models.CharField):

    def __init__(self, embedded_model=None, *args, **kwargs):
        self.embedded_model = embedded_model
        kwargs.setdefault('default', None)
        super(PartialReferenceField, self).__init__(*args, **kwargs)


    def get_internal_type(self):
        return 'PartialReferenceField'