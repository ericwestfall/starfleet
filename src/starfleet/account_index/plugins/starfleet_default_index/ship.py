"""The Starfleet Default Account Index Plugin

This is the default Starfleet Account Index Plugin that is based on the AccountIndexGeneratorShip plugin. The AccountIndexGeneratorShip generates an account index
file to S3, and this plugin uses that generated file as the basis for the account index.

:Module: starfleet.account_index.plugins.starfleet_default_index.ship
:Copyright: (c) 2023 by Gemini Trust Company, LLC., see AUTHORS for more info
:License: See the LICENSE file for details
:Author: Mike Grima <michael.grima@gemini.com>
"""
# pylint: disable=too-many-locals,too-many-statements
import json
from typing import Set, Dict, Any
from sys import intern

import boto3
from botocore.exceptions import ClientError
from marshmallow import Schema, fields, ValidationError

from starfleet.account_index.schematics import AccountIndex
from starfleet.utils.configuration import STARFLEET_CONFIGURATION
from starfleet.utils.logging import LOGGER


class StarfleetDefaultAccountIndexSchema(Schema):
    """This is the configuration schema required for the StarfleetDefaultAccountIndex."""

    index_bucket = fields.String(required=True, data_key="IndexBucket")
    bucket_region = fields.String(required=True, data_key="BucketRegion")
    index_object_path = fields.String(required=False, data_key="IndexObjectPath", load_default="accountIndex.json")


class MissingConfigurationError(Exception):
    """Exception raised if the configuration for the StarfleetDefaultAccountIndex configuration entry is missing."""


class StarfleetDefaultAccountIndex(AccountIndex):
    """
    This is the default account index plugin that uses the generated account index from the AccountIndexGeneratorShip Starfleet Worker Ship.

    TODO: Should we make the generated index from the AccountIndexGeneratorShip a Marshmallow schema?
    """

    def __init__(self):
        """
        This will go out to S3 and load the configuration that is needed. Since this has a dependency on the AccountIndexGeneratorShip worker to generate the files to S3.
        This will need a configuration that tells it where to download the Account Index JSON.
        """
        self.org_root = ""
        self.account_ids = set()
        self.alias_map: Dict[str, str] = {}
        self.ou_map: Dict[str, Set[str]] = {}
        self.regions_map: Dict[str, Set[str]] = {}
        self.tag_map: Dict[str, Dict[str, Set[str]]] = {}  # Dict of tag name -> tag value -> accounts

        LOGGER.debug("[⚙️] Loading the StarfleetDefaultAccountIndex...")
        try:
            config = StarfleetDefaultAccountIndexSchema().load(STARFLEET_CONFIGURATION.config["StarfleetDefaultAccountIndex"])

            LOGGER.debug(
                f"[🪣] Fetching the index from the S3 bucket: {config['index_bucket']}, region: {config['bucket_region']}, path: {config['index_object_path']}..."
            )
            client = boto3.client("s3", region_name=config["bucket_region"])
            account_dict = json.loads(client.get_object(Bucket=config["index_bucket"], Key=config["index_object_path"])["Body"].read())
            self._load_inventory(account_dict)
            LOGGER.debug("[🆗] Index loaded.")

        except KeyError as kerr:
            LOGGER.error("[💥] Missing the StarfleetDefaultAccountIndex configuration field in the configuration YAMLs. Cannot proceed.")
            raise MissingConfigurationError() from kerr

        except ValidationError as verr:
            LOGGER.error("[💥] Invalid configuration entry for the StarfleetDefaultAccountIndex. Error details:")
            LOGGER.exception(verr)
            raise

        except ClientError as cerr:
            LOGGER.error("[💥] Unable to fetch the index object from S3. Error details:")
            LOGGER.exception(cerr)
            raise

        except Exception as exc:  # noqa
            LOGGER.error(
                "[💥] Received some other problem decoding the account index. Note: This *NEEDS* to be the object generated by the AccountIndexGeneratorShip plugin."
            )
            LOGGER.exception(exc)
            raise

    def _load_inventory(self, account_dict: Dict[str, Any]) -> None:
        """Utility function to perform all the inventory loading."""
        # Generate the mappings:
        for account_id, account in account_dict.items():
            # Add to the Account ID Mapping:
            self.account_ids.add(intern(account_id))  # Using intern for all IDs for memory and performance -- which might improve things?

            # Create the proper mapping for each account alias:
            self.alias_map[account["Name"].lower()] = intern(account_id)
            # TODO: Add in something with an alias tag to populate this

            # Create the regions mapping:
            for region in account["Regions"]:
                mapping = self.regions_map.get(region, set())
                mapping.add(intern(account_id))
                self.regions_map[region] = mapping

            # Create the OU mapping:
            for org_unit in account["Parents"]:
                # We are assuming that the OU names and IDs are not the same LOL
                ou_id = org_unit["Id"].lower()
                ou_name = org_unit["Name"].lower()
                mapping_id = self.ou_map.get(ou_id, set())
                mapping_name = self.ou_map.get(ou_name, set())
                mapping_id.add(intern(account_id))
                mapping_name.add(intern(account_id))
                self.ou_map[ou_id] = mapping_id
                self.ou_map[ou_name] = mapping_id

            # Create the tag mapping:
            for tag_name, tag_value in account["Tags"].items():
                norm_tag_name = tag_name.lower()
                norm_tag_value = tag_value.lower()
                tag_name_mapping = self.tag_map.get(norm_tag_name, {})
                tag_value_mapping = tag_name_mapping.get(norm_tag_value, set())
                tag_value_mapping.add(intern(account_id))
                tag_name_mapping[norm_tag_value] = tag_value_mapping
                self.tag_map[norm_tag_name] = tag_name_mapping

        # This worker operates in one AWS Org. The Organization root is in the ARN for an account in the Org, and looks like this:
        # arn:aws:organizations::ORG-ROOT-ACCOUNT-ID:account/ORG-ID/ACCOUNT-ID
        #                        ^^ We are going to pull this out of the last account in the list.

        # Pull out the first account in the dict and parse out the ARN:
        some_account = next(iter(account_dict.values()))
        self.org_root = some_account["Arn"].split("arn:aws:organizations::")[1].split(":")[0]

    def get_accounts_by_ids(self, ids: Set[str]) -> Set[str]:
        """Return back a Set of account IDs for a given Set of IDs present -- this effectively only returns back account IDs that exist in the inventory."""
        return ids.intersection(self.account_ids)

    def get_accounts_by_aliases(self, aliases: Set[str]) -> Set[str]:
        """Return back a Set of account IDs for a given Set of aliases"""
        accounts = set()
        for alias in aliases:
            account = self.alias_map.get(alias.lower(), None)
            if account:
                accounts.add(account)

        return accounts

    def get_accounts_by_tag(self, tag_name: str, tag_value: str) -> Set[str]:
        """Return back a set of account IDs based on the tag name and value pair"""
        return self.tag_map.get(tag_name.lower(), {}).get(tag_value.lower(), set())

    def get_accounts_by_ou(self, org_unit: str) -> Set[str]:
        """Return back a set of account IDs based on the OU membership"""
        return self.ou_map.get(org_unit.lower(), set())

    def get_accounts_by_regions(self, regions: Set[str]) -> Dict[str, Set[str]]:
        """Return back a dictionary of the region and the set of accounts associated with it."""
        mapping = {}
        for region in regions:
            mapping[region] = self.regions_map.get(region, set())

        return mapping

    def get_accounts_for_all_regions(self) -> Dict[str, Set[str]]:
        """Return back a dictionary of the region and the set of all accounts associated with it -- but for ALL regions."""
        return self.regions_map

    def get_all_accounts(self) -> Set[str]:
        """Return back a set of all account IDs."""
        return self.account_ids

    def get_org_roots(self) -> Set[str]:
        """
        Return back the set of account IDs for Organization Root accounts. This is mostly used for the Account and Account/Region worker ships when specifying if the payload
        in question should operate in an AWS Organization Root account. If the flag in the template is set, then this will check if there is an Organization Root set and task a
        worker ship with the payload to operate in that corresponding organization root.

        Note: This AccountIndex plugin assumes that there is exactly 1 AWS Organization that is being used.
        """
        return {self.org_root}
