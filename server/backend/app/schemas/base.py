from bson import ObjectId
from pydantic import Field
from pydantic_core import core_schema
from pydantic import GetCoreSchemaHandler, GetJsonSchemaHandler

class PyObjectId(ObjectId):
    @classmethod
    def __get_pydantic_core_schema__(  # ← hook for validation/coercion
        cls, source_type: type, handler: GetCoreSchemaHandler
    ) -> core_schema.CoreSchema:
        # use no_info_plain_validator_function to wrap our `.validate()`
        return core_schema.no_info_plain_validator_function(cls.validate)

    @classmethod
    def __get_pydantic_json_schema__(
        cls, 
        core_schema_obj: core_schema.CoreSchema,      # the core schema for this type
        handler: GetJsonSchemaHandler
    ) -> dict:  # ← hook for JSON schema
        return {"type": "string"}

    @classmethod
    def validate(cls, v, info=None):
        # accept both strings and ObjectId
        if isinstance(v, ObjectId):
            return v
        if not ObjectId.is_valid(v):
            raise ValueError("Invalid ObjectId")
        return ObjectId(v)
