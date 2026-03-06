# Copyright (c) 2025-2025 Sunet.
# Contributor: Kristofer Hallin
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from pydantic import BaseModel
from typing import Optional


class TranscriptionStatusPut(BaseModel):
    language: Optional[str] = None
    speakers: Optional[int] = 0
    output_format: Optional[str] = None
    encryption_password: Optional[str] = None


class TranscriptionResultPut(BaseModel):
    format: Optional[str] = None
    data: Optional[str] = None


class ModifyUserRequest(BaseModel):
    active: Optional[bool] = None
    admin: Optional[bool] = None
    admin_domains: Optional[str] = None


class CreateGroupRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    quota_seconds: Optional[int] = 0


class UpdateGroupRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    usernames: Optional[list] = []
    quota_seconds: Optional[int] = 0
    quota: Optional[int] = 0


class CreateCustomerRequest(BaseModel):
    customer_abbr: Optional[str] = None
    partner_id: str
    name: str
    priceplan: Optional[str] = "variable"
    base_fee: Optional[float] = 0
    realms: Optional[str] = ""
    contact_email: Optional[str] = ""
    notes: Optional[str] = ""
    blocks_purchased: Optional[int] = 0


class UpdateCustomerRequest(BaseModel):
    customer_abbr: Optional[str] = None
    partner_id: Optional[str] = None
    name: Optional[str] = None
    priceplan: Optional[str] = None
    base_fee: Optional[float] = None
    realms: Optional[str] = None
    contact_email: Optional[str] = None
    notes: Optional[str] = None
    blocks_purchased: Optional[int] = None


class TranscribeExternalPost(BaseModel):
    language: Optional[str]
    model: Optional[str]
    output_format: Optional[str]
    user_id: Optional[str]
    file_url: Optional[str]
    id: Optional[str]
    service_id: Optional[str]


class VideoStreamRequestBody(BaseModel):
    encryption_password: Optional[str] = ""


class NotificationSettings(BaseModel):
    notify_on_job: Optional[bool] = None
    notify_on_deletion: Optional[bool] = None
    notify_on_user: Optional[bool] = None


class UserUpdateRequest(BaseModel):
    email: Optional[str] = None
    encryption_password: Optional[str] = None
    encryption: Optional[bool] = False
    notifications: Optional[NotificationSettings] = None
    reset_password: Optional[bool] = False
    verify_password: Optional[bool] = False


class TranscriptionJobUpdateRequest(BaseModel):
    status: Optional[str] = None
    error: Optional[str] = None
    transcribed_seconds: Optional[float] = None


class TranscriptionResultRequest(BaseModel):
    format: str = ""
    result: str | dict
