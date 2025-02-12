"""Tests for the AWS Config worker's schemas

Tests out the schemas for configuration and payload to make sure they are correct.

:Module: starfleet.tests.starfleet_included_plugins.aws_config.test_schemas
:Copyright: (c) 2023 by Gemini Trust Company, LLC., see AUTHORS for more info
:License: See the LICENSE file for details
:Author: Mike Grima <michael.grima@gemini.com>
"""
# pylint: disable=unused-argument
import boto3

import pytest
import yaml
from marshmallow import ValidationError


def test_delivery_channel_details_schema() -> None:
    """This tests that the DeliveryChannelDetails schema has proper validation."""
    from starfleet.worker_ships.plugins.aws_config.schemas import DeliveryChannelDetails, DeliveryFrequency

    # Good (required only):
    payload = """
        BucketName: some-bucket
        S3DeliveryFrequency: Twelve_Hours
    """
    assert DeliveryChannelDetails().load(yaml.safe_load(payload)) == {
        "bucket_name": "some-bucket",
        "s3_delivery_frequency": DeliveryFrequency.Twelve_Hours,
        "bucket_key_prefix": None,
        "preferred_name": "default",
        "s3_kms_key_arn": None,
        "sns_topic_arn": None,
    }

    # Good (All fields):
    payload = """
        BucketName: some-bucket
        S3DeliveryFrequency: Twelve_Hours
        BucketKeyPrefix: some/prefix/
        S3KmsKeyArn: arn:aws:kms:us-east-1:012345678912:key/1234abcd-1234ab-34cd-56ef-1234567890ab
        SnsTopicArn: arn:aws:sns:us-east-1:012345678912:topic/some-topic
        PreferredName: not-default
    """
    assert DeliveryChannelDetails().load(yaml.safe_load(payload))

    # Bad (missing required field):
    payload = """
        S3DeliveryFrequency: Twelve_Hours
    """
    with pytest.raises(ValidationError):
        DeliveryChannelDetails().load(yaml.safe_load(payload))

    # Bad (Invalid delivery frequency):
    payload = """
        S3DeliveryFrequency: pew-pew-pew
    """
    with pytest.raises(ValidationError):
        DeliveryChannelDetails().load(yaml.safe_load(payload))


def test_recording_group_schema() -> None:
    """This tests that the RecordingGroup schema has proper validation logic."""
    from starfleet.worker_ships.plugins.aws_config.schemas import RecordingGroup

    # Without specifying a resource type
    payload = """
        ResourceTypes: []  # Empty, which is bad
        GlobalsInRegions:
            - us-east-1  # Doesn't matter
    """
    with pytest.raises(ValidationError) as exc:
        RecordingGroup().load(yaml.safe_load(payload))
    assert exc.value.messages == {"ResourceTypes": ["Shorter than minimum length 1."]}

    # Specifying ALL and other things:
    payload = """
        ResourceTypes:
          - some::resource::type
          - ALL
          - some::other::resource
    """
    with pytest.raises(ValidationError) as exc:
        RecordingGroup().load(yaml.safe_load(payload))
    assert exc.value.messages == {"IncludeRegions": ["Can't specify any other resource types when `ALL` is specified in the list."]}

    # Specifying ALL and regions that don't exist:
    payload = """
        ResourceTypes:
          - ALL
        GlobalsInRegions:
            - us-east-1
            - not-a-region
            - us-east-2
            - pew-pew-pew
    """
    with pytest.raises(ValidationError) as exc:
        RecordingGroup().load(yaml.safe_load(payload))
    for bad_region in ["not-a-region", "pew-pew-pew"]:
        assert bad_region in exc.value.messages["GlobalsInRegions"][0]

    # Specifying specific resources and also the GlobalsInRegions parameter:
    payload = """
        ResourceTypes:
          - AWS::S3::Bucket
        GlobalsInRegions:
            - us-east-1
    """
    with pytest.raises(ValidationError) as exc:
        RecordingGroup().load(yaml.safe_load(payload))
    assert exc.value.messages == {"GlobalsInRegions": ["This field can only be specified with a list of regions if `ResourceTypes` is set to `- ALL`"]}

    # Good (all):
    payload = """
        ResourceTypes:
          - ALL
        GlobalsInRegions:
            - us-east-1
    """
    assert RecordingGroup().load(yaml.safe_load(payload)) == {"resource_types": ["ALL"], "globals_in_regions": ["us-east-1"]}

    # Good (not all)
    payload = """
        ResourceTypes:
          - AWS::S3::Bucket
          - AWS::IAM::Role
    """
    assert RecordingGroup().load(yaml.safe_load(payload)) == {"resource_types": ["AWS::S3::Bucket", "AWS::IAM::Role"]}


def test_recorder_configuration_schema() -> None:
    """This tests that the RecorderConfiguration schema has proper validation logic."""
    from starfleet.worker_ships.plugins.aws_config.schemas import RecorderConfiguration

    # Good:
    payload = """
        ConfigRoleName: AWSConfigRole
        RecordingEnabled: True
        RecordingGroup:
            ResourceTypes:
                - ALL
            GlobalsInRegions:
                - us-east-1
    """
    assert RecorderConfiguration().load(yaml.safe_load(payload)) == {
        "config_role_name": "AWSConfigRole",
        "recording_enabled": True,
        "recording_group": {"resource_types": ["ALL"], "globals_in_regions": ["us-east-1"]},
        "preferred_name": "default",
    }

    # Bad:
    with pytest.raises(ValidationError) as exc:
        RecorderConfiguration().load(yaml.safe_load("PreferredName: PewPewPew"))
    assert exc.value.messages == {"ConfigRoleName": ["Missing data for required field."], "RecordingGroup": ["Missing data for required field."]}


def test_all_accounts_configuration() -> None:
    """This tests that the DefaultConfiguration schema has proper validation logic."""
    from starfleet.worker_ships.plugins.aws_config.schemas import DefaultConfiguration

    # Good:
    payload = """
        DeliveryChannelDetails:
            BucketName: some-bucket
            S3DeliveryFrequency: Twelve_Hours
            BucketKeyPrefix: some/prefix/
            S3KmsKeyArn: arn:aws:kms:us-east-1:012345678912:key/1234abcd-1234ab-34cd-56ef-1234567890ab
            SnsTopicArn: arn:aws:sns:us-east-1:012345678912:topic/some-topic
            PreferredName: not-default
        RecorderConfiguration:
            ConfigRoleName: AWSConfigRole
            RecordingEnabled: True
            RecordingGroup:
                ResourceTypes:
                    - ALL
                GlobalsInRegions:
                    - us-east-1
        RetentionPeriodInDays: 30
    """
    # Just verify that some of the fields are good:
    loaded = DefaultConfiguration().load(yaml.safe_load(payload))
    assert loaded["delivery_channel_details"]["bucket_name"] == "some-bucket"
    assert loaded["recorder_configuration"]["recording_group"]["resource_types"] == ["ALL"]

    # Exclude the required things:
    with pytest.raises(ValidationError) as exc:
        DefaultConfiguration().load({})
    assert exc.value.messages == {
        "DeliveryChannelDetails": ["Missing data for required field."],
        "RecorderConfiguration": ["Missing data for required field."],
        "RetentionPeriodInDays": ["Missing data for required field."],
    }


def test_account_override_configuration() -> None:
    """This tests that the AccountOverrideConfiguration schema has proper validation logic."""
    from starfleet.worker_ships.plugins.aws_config.schemas import AccountOverrideConfiguration

    # Good:
    payload = """
        IncludeAccounts:
            ByNames:
                - Some Enabled Account
        IncludeRegions:
            - ALL
        ExcludeRegions:
            - us-west-1
        ExcludeAccounts:
            ByNames:
                - Some Disabled Account
        DeliveryChannelDetails:
            BucketName: some-bucket
            S3DeliveryFrequency: Twelve_Hours
            BucketKeyPrefix: some/prefix/
            S3KmsKeyArn: arn:aws:kms:us-east-1:012345678912:key/1234abcd-1234ab-34cd-56ef-1234567890ab
            SnsTopicArn: arn:aws:sns:us-east-1:012345678912:topic/some-topic
            PreferredName: not-default
        RecorderConfiguration:
            ConfigRoleName: AWSConfigRole
            RecordingEnabled: True
            RecordingGroup:
                ResourceTypes:
                    - ALL
                GlobalsInRegions:
                    - us-east-1
        RetentionPeriodInDays: 2557
    """
    # Just verify that some of the fields are good:
    loaded = AccountOverrideConfiguration().load(yaml.safe_load(payload))
    assert loaded["include_accounts"]["by_names"] == ["Some Enabled Account"]
    assert loaded["include_regions"] == set(boto3.session.Session().get_available_regions("config"))
    assert loaded["exclude_regions"] == {"us-west-1"}
    assert loaded["exclude_accounts"]["by_names"] == ["Some Disabled Account"]
    assert loaded["delivery_channel_details"]["bucket_name"] == "some-bucket"
    assert loaded["recorder_configuration"]["recording_group"]["resource_types"] == ["ALL"]

    # Good with specific regions mentioned:
    good_regions = yaml.safe_load(payload)
    good_regions["IncludeRegions"] = ["us-east-1", "us-east-2"]
    loaded = AccountOverrideConfiguration().load(good_regions)
    assert loaded["include_regions"] == {"us-east-1", "us-east-2"}

    # Now, confirm the exclude/include region logic with bad regions:
    with pytest.raises(ValidationError) as exc:
        bad_regions = yaml.safe_load(payload)
        bad_regions["ExcludeRegions"].append("pewpewpew")
        bad_regions["IncludeRegions"] = ["pewpewpew"]
        AccountOverrideConfiguration().load(bad_regions)
    assert exc.value.messages["ExcludeRegions"][0].startswith("Invalid regions are specified: pewpewpew.")
    assert exc.value.messages["IncludeRegions"][0].startswith("Invalid regions are specified: pewpewpew.")

    # Specify region to include in addition to ALL:
    with pytest.raises(ValidationError) as exc:
        bad_regions = yaml.safe_load(payload)
        bad_regions["IncludeRegions"] = ["us-east-1", "ALL"]
        AccountOverrideConfiguration().load(bad_regions)
    assert exc.value.messages == {"IncludeRegions": ["Can't specify any other regions when `ALL` is specified in the list."]}

    # Exclude the required things:
    with pytest.raises(ValidationError) as exc:
        AccountOverrideConfiguration().load({})
    assert exc.value.messages == {
        "DeliveryChannelDetails": ["Missing data for required field."],
        "IncludeAccounts": ["Missing data for required field."],
        "IncludeRegions": ["Missing data for required field."],
        "RecorderConfiguration": ["Missing data for required field."],
        "RetentionPeriodInDays": ["Missing data for required field."],
    }


def test_payload_template() -> None:
    """This tests that the AwsConfigWorkerShipPayloadTemplate schema has proper validation logic."""
    from starfleet.worker_ships.plugins.aws_config.schemas import AwsConfigWorkerShipPayloadTemplate

    # Good:
    payload = """
        TemplateName: AWSConfig
        TemplateDescription: Enabled AWS Config Everywhere
        IncludeAccounts:
            AllAccounts: True
        IncludeRegions:
            - ALL
        DefaultConfiguration:
            DeliveryChannelDetails:
                BucketName: some-bucket
                S3DeliveryFrequency: Twelve_Hours
            RecorderConfiguration:
                ConfigRoleName: AWSConfigRole
                RecordingEnabled: True
                RecordingGroup:
                    ResourceTypes:
                        - ALL
                    GlobalsInRegions:
                        - us-east-1
            RetentionPeriodInDays: 2557
        # For Some Override Account, we just want to record S3 buckets in all regions except for us-west-1:
        AccountOverrideConfigurations:
            -
                IncludeAccounts:
                    ByNames:
                        - Some Override Account
                IncludeRegions:
                    - ALL
                ExcludeRegions:
                    - us-west-1
                DeliveryChannelDetails:
                    BucketName: some-bucket
                    S3DeliveryFrequency: Twelve_Hours
                RecorderConfiguration:
                    ConfigRoleName: AWSConfigRole
                    RecordingEnabled: True
                    RecordingGroup:
                        ResourceTypes:
                            - AWS::S3::Bucket
                RetentionPeriodInDays: 2557
    """
    # Just confirm that we can load it all:
    assert AwsConfigWorkerShipPayloadTemplate().load(yaml.safe_load(payload))

    # Confirm missing stuff:
    with pytest.raises(ValidationError) as exc:
        payload = """
            TemplateName: AWSConfig
            TemplateDescription: Enabled AWS Config Everywhere
            IncludeAccounts:
                AllAccounts: True
            IncludeRegions:
                - ALL
        """
        AwsConfigWorkerShipPayloadTemplate().load(yaml.safe_load(payload))
    assert exc.value.messages == {"DefaultConfiguration": ["Missing data for required field."]}
