#!/usr/bin/env python3
from typing import List, Tuple, Optional, Union, Dict
from pathlib import Path
import docker
import requests
import json
import time
import sys
import subprocess
from engine_handler.handler import EngineHandler
from api_communication.proto import catalog_pb2 as api_catalog
from api_communication.proto import engine_pb2 as api_engine
from api_communication.proto import policy_pb2 as api_policy
from google.protobuf.json_format import ParseDict
import shared.resource_handler as rs


class UnitOutput:
    def __init__(self, index: int, result: Union[str, dict]):
        self.index = index
        if isinstance(result, str):
            self.success = False
            self.error = result
        elif isinstance(result, dict):
            self.success = True
            self.output = result


class UnitResult:
    def __init__(self, index: int, expected: dict, actual: dict):
        self.index = index
        self.expected = expected
        self.setup(actual)

    def setup(self, actual: dict):
        self.diff = {}
        if self.expected == actual:
            self.success = True
            return
        else:
            self.success = False

        for key in self.expected:
            if key not in actual:
                self.diff[key] = {"info": "Missing key in actual result",
                                  "expected": self.expected[key]}
            elif self.expected[key] != actual[key]:
                self.diff[key] = {"info": "Mismatched value",
                                  "expected": self.expected[key], "actual": actual[key]}
        for key in actual:
            if key not in self.expected:
                self.diff[key] = {"info": "Extra key in actual result",
                                  "actual": actual[key]}


class UnitOutput:
    def __init__(self, index: int, result: Union[str, dict]):
        self.index = index
        if isinstance(result, str):
            self.success = False
            self.error = result
        elif isinstance(result, dict):
            self.success = True
            self.output = result


class EngineTestOutput:
    def __init__(self, name: str, command: str):
        self.name = name
        self.command = command
        self.results: List[UnitOutput] = []

    def add_result(self, result: UnitOutput):
        self.results.append(result)


class TestResult:
    def __init__(self, name: str, command: Optional[str] = None):
        self.name = name
        self.results: List[UnitResult] = []
        self.success = True
        self.test_error = None
        self.command = command

    def add_result(self, result: UnitResult):
        self.results.append(result)
        if not result.success:
            self.success = False

    def make_failure(self, error: str):
        self.success = False
        self.test_error = error


class Result:
    def __init__(self, name: str):
        self.name = name
        self.results: List[TestResult] = []
        self.success = True
        self.test_error = None

    def add_result(self, result: TestResult):
        self.results.append(result)
        if not result.success:
            self.success = False

    def make_failure(self, error: str):
        self.success = False
        self.test_error = error

    def __str__(self) -> str:
        out = f"{self.name} -> {'Success' if self.success else 'Failure'}"
        if self.test_error:
            out += f"\n  Error: {self.test_error}"
        elif not self.success:
            for result in self.results:
                out += f"\n  {result.name} -> {'Success' if result.success else 'Failure'}"
                if not result.success and result.command:
                    out += f"\n    Command: {result.command}"
                if result.test_error:
                    out += f"\n    Error: {result.test_error}"
                elif not result.success:
                    out += "\n    Event index:"
                    for unit_result in result.results:
                        out += f"\n      {unit_result.index} -> {'Success' if unit_result.success else 'Failure'}"
                        if not unit_result.success:
                            for key, value in unit_result.diff.items():
                                out += f"\n        {key}: {value}"

        return out


class OpensearchManagement:
    def __init__(self):
        self.offset = 0

    def stop(self):
        for container in self.client.containers.list():
            try:
                container.stop()
                container.remove()
            except Exception as e:
                print(f"Error stopping or removing container {container.id}: {e}")
        self.client.containers.prune()

    def init_index(self, template_path: Path) -> requests.Response:
        with open(template_path, 'r') as template_file:
            template_json = json.load(template_file)
            headers = {"Content-Type": "application/json"}
            url = f'http://localhost:9200/test-basic-index'
            response = requests.put(url, data=json.dumps(template_json['template']), headers=headers)
            return response

    def init_opensearch(self, template_path: Path):
        self.client = docker.from_env()
        env_vars = {
            'discovery.type': 'single-node',
            'plugins.security.disabled': 'true',
            'OPENSEARCH_INITIAL_ADMIN_PASSWORD': 'WazuhTest99$',
            'OPENSEARCH_LOG_LEVEL': 'TRACE'
        }
        self.client.containers.run("opensearchproject/opensearch", detach=True, ports={'9200/tcp': 9200},
                                   environment=env_vars, name='opensearch', stdout=True, stderr=True)

        while True:
            try:
                response = requests.get('http://localhost:9200')
                if response.status_code == 200:
                    if self.init_index(template_path).status_code == 200:
                        break
            except requests.exceptions.ConnectionError:
                pass
            time.sleep(1)

        try:
            url_health = 'http://localhost:9200/_cluster/health?wait_for_status=green&timeout=10s'
            response = requests.get(url_health)
            response.raise_for_status()
            assert response.status_code == 200, f"Expected status code 200, but got {response.status_code}"
            assert response.json()['status'] == 'green', f"Expected status 'green', but got {response.json()['status']}"
            counter = 0
            while counter < 10:
                url = 'http://localhost:9200/_cat/indices'
                response = requests.get(url)
                if response.status_code == 200 and 'test-basic-index' in response.text:
                    break
                time.sleep(1)
                counter += 1
            assert counter < 10, "The index was not created"

        except requests.RequestException as e:
            print(f"HTTP request error: {e}")
            self.stop()
        except AssertionError as e:
            print(f"Assertion error: {e}")
            self.stop()
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            self.stop()

    def check_custom_fields(self, custom_fields: dict, all_custom_fields: set, hits: list):
        def get_nested_value(d: dict, keys: list):
            for key in keys:
                if isinstance(d, dict) and key in d:
                    d = d[key]
                elif isinstance(d, list):
                    try:
                        index = int(key)
                        d = d[index]
                    except (ValueError, IndexError):
                        return None
                else:
                    return None
            return d

        def normalize_field(field):
            return '.'.join(part.split('[')[0] for part in field.split('.'))

        def matches_type(value, expected_type):
            if expected_type == 'array':
                return isinstance(value, list)
            elif expected_type == 'object':
                return isinstance(value, dict)
            elif expected_type == 'keyword':
                return isinstance(value, (str, int, float))
            return False

        found_fields = set()

        for hit in hits:
            for field in custom_fields:
                normalized_field = normalize_field(field)
                field_keys = normalized_field.split('.')

                value = get_nested_value(hit['_source'], field_keys)
                if value is not None and matches_type(value, custom_fields[field]):
                    found_fields.add(field)

        for field in found_fields:
            field_type = custom_fields.get(field)

            if field_type in {'object', 'array'}:
                prefix = field if field_type == 'object' else field + '.'
                to_remove = {f for f in all_custom_fields if f == field or f.startswith(prefix)}
                all_custom_fields.difference_update(to_remove)
            else:
                all_custom_fields.discard(field)

    def read_index(self, result: Result, custom_fields: dict, all_custom_fields: set, outputs_number: int, retries=10, delay=4):
        url_search = 'http://localhost:9200/test-basic-index/_search'
        headers = {"Content-Type": "application/json"}
        terminate = False
        for attempt in range(retries):
            try:
                query = {
                    "size": 1000,
                    "query": {
                        "match_all": {}
                    }
                }

                response = requests.post(url_search, json=query, headers=headers)
                response.raise_for_status()
                hits = response.json()['hits']['hits']
                if len(hits) == outputs_number:
                    terminate = True
                    self.check_custom_fields(custom_fields, all_custom_fields, hits)
                    break
                else:
                    print(f"{len(hits)} documents found out of {outputs_number} pushed. Retrying")
            except requests.ConnectionError as e:
                print(f"Connection error: {e}. Retrying...")

            time.sleep(delay)

        if not terminate:
            sys.exit(f"{outputs_number - len(hits)} items not found")


opensearch_management = OpensearchManagement()


def extract_fields(data, prefix=""):
    fields = []
    if isinstance(data, dict):
        for key, value in data.items():
            new_prefix = f"{prefix}.{key}" if prefix else key
            fields.extend(extract_fields(value, new_prefix))
    elif isinstance(data, list):
        for item in data:
            fields.extend(extract_fields(item, prefix))
    else:
        fields.append(prefix)
    return fields


def add_custom_fields(custom_fields: set, data_list, schema_fields):
    for data_str in data_list:
        try:
            data = json.loads(data_str)
            extracted_fields = extract_fields(data)

            for field in extracted_fields:
                if field not in schema_fields:
                    custom_fields.add(field)
        except json.JSONDecodeError as e:
            print(f"Error decoding JSON: {e}")


def execute(name: str, command: str, customs: set, schema_fields: list) -> Tuple[Optional[str], EngineTestOutput]:
    result = EngineTestOutput(name, command)
    try:
        output = subprocess.check_output(
            command, shell=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        return f"Error executing command: {e.output.decode()}", result

    output_str = output.decode('utf-8')
    json_strings = output_str.strip().split('\n')

    add_custom_fields(customs, json_strings, schema_fields)

    for i, json_string in enumerate(json_strings):
        try:
            parsed_json = json.loads(json_string)
        except json.JSONDecodeError as e:
            result.add_result(UnitOutput(i, f"Error parsing JSON: {e}"))
        else:
            result.add_result(UnitOutput(i, parsed_json))

    return None, result


def test(input_file: Path, command: str, customs: set, schema_fields: list) -> EngineTestOutput:
    name = input_file.stem.replace("_input", "")
    error, output = execute(name, command, customs, schema_fields)

    if error:
        print(error)
        print("F", end="", flush=True)
        output.add_result(UnitOutput(0, error))
    else:
        print(".", end="", flush=True)

    return output


def run_all_tests(test_parent_paths: List[Path],
                  engine_api_socket: str, schema_fields) -> Tuple[Dict[str, List[EngineTestOutput]],
                                                                  int, set]:
    all_outputs_by_integration = {}
    number_outputs = 0
    customs = set()

    for test_parent_path in test_parent_paths:
        test_parent_name = test_parent_path.name
        test_dir = (test_parent_path / "test").resolve()

        if not test_dir.exists():
            print(f"Test directory not found: {test_dir}")
            continue

        engine_test_conf = test_parent_path / "test" / "engine-test.conf"
        if not engine_test_conf.exists():
            print(f"engine-test.conf not found: {engine_test_conf}")
            continue

        outputs_for_integration = []

        for input_file in test_dir.rglob("*_input.*"):
            test_name = test_parent_name
            if input_file.parent != test_dir:
                test_name = f"{test_parent_name}-{input_file.parent.name}"
            engine_test_command = f"engine-test -c {engine_test_conf.resolve().as_posix()} run {test_name} --api-socket {engine_api_socket} -j"
            command = f"cat {input_file.resolve().as_posix()} | {engine_test_command}"

            output = test(input_file, command, customs, schema_fields)
            number_outputs += len(output.results)
            outputs_for_integration.append(output)

        all_outputs_by_integration[test_parent_name] = outputs_for_integration

    return all_outputs_by_integration, number_outputs, customs


def validate_custom_fields(
        integration: str, custom_fields: dict, all_custom_fields: set, outputs_number: int) -> Result:
    result = Result(integration)
    opensearch_management.read_index(result, custom_fields, all_custom_fields, outputs_number)

    return result


def load_custom_fields(custom_fields_path):
    """
    Load custom fields from 'custom_fields.yml' and return a dictionary
    where keys are the field names and values are their types.
    """
    try:
        custom_fields_data = rs.ResourceHandler().load_file(custom_fields_path.as_posix())
        return {item['field']: item['type'] for item in custom_fields_data}

    except Exception as e:
        sys.exit(f"Error loading custom fields from {custom_fields_path}: {e}")
        return {}


def run_test(test_parent_paths: List[Path], engine_api_socket: str, schema_fields) -> List[Result]:
    outputs, number_outputs, all_custom_fields = run_all_tests(test_parent_paths, engine_api_socket, schema_fields)
    results = []

    for custom_field_container in test_parent_paths:
        if custom_field_container.name != 'wazuh-core':
            custom_fields_path = custom_field_container / 'test' / 'custom_fields.yml'
            if not custom_fields_path.exists():
                sys.exit(custom_field_container.name, str(custom_fields_path),
                         "Error: custom_fields.yml file does not exist.")
            custom_fields = load_custom_fields(custom_fields_path)
            results.append(validate_custom_fields(custom_field_container.name,
                           custom_fields, all_custom_fields, number_outputs))

    if all_custom_fields:
        sys.exit(f"The following fields were not found or matched incorrectly: {all_custom_fields}")

    return results


def exist_index_output(engine_handler: EngineHandler):
    request = api_catalog.ResourceGet_Request()
    request.namespaceid = "system"
    request.name = "output/indexer/0"
    request.format = api_catalog.ResourceFormat.yml
    error, response = engine_handler.api_client.send_recv(request)
    if error:
        raise Exception(error)

    parsed_response = ParseDict(response, api_catalog.ResourceGet_Response())
    if parsed_response.content != "":
        return True
    return False


def load_indexer_output(engine_handler: EngineHandler) -> None:
    indexer_output = {
        "name": "output/indexer/0",
        "metadata": {
            "title": "Indexer output event",
            "description": "Output integrations events to wazuh-indexer",
            "compatibility": "",
            "versions": [""],
            "references": [""],
            "author": {
                "name": "Wazuh, Inc.",
                "date": "2024/12/01"
            }
        },
        "check": "not_exists($wazuh.noIndexing) OR $wazuh.noIndexing == false",
        "outputs": [
            {
                "wazuh-indexer": {
                    "index": "alerts"
                }
            }
        ]
    }

    request = api_catalog.ResourcePost_Request()
    request.type = api_catalog.ResourceType.output
    request.namespaceid = "system"
    request.content = json.dumps(indexer_output)
    request.format = api_catalog.ResourceFormat.json
    print(f"Loading indexer output...\n{request}")
    error, response = engine_handler.api_client.send_recv(request)
    if error:
        raise Exception(error)

    parsed_response = ParseDict(
        response, api_engine.GenericStatus_Response())
    if parsed_response.status == api_engine.ERROR:
        raise Exception(parsed_response.error)
    print(f"Indexer output loaded.")


def load_indexer_output_in_policy(engine_handler: EngineHandler, stop_on_warn: bool = True) -> None:
    request = api_policy.AssetPost_Request()
    request.asset = "output/indexer/0"
    request.policy = "policy/wazuh/0"
    request.namespace = "system"
    print(f"Adding indexer output to policy...\n{request}")
    error, response = engine_handler.api_client.send_recv(request)
    if error:
        raise Exception(error)
    parsed_response = ParseDict(response, api_policy.AssetPost_Response())
    if parsed_response.status == api_engine.ERROR:
        raise Exception(parsed_response.error)
    if len(parsed_response.warning) > 0 and stop_on_warn:
        raise Exception(parsed_response.warning)
    print("indexer output added to policy.")


def delete_indexer_output(engine_handler: EngineHandler) -> None:
    request = api_catalog.ResourceDelete_Request()
    request.name = "output/indexer/0"
    request.namespaceid = "system"
    print(f"Deleting indexer output...\n{request}")
    error, response = engine_handler.api_client.send_recv(request)
    if error:
        raise Exception(error)

    parsed_response = ParseDict(
        response, api_engine.GenericStatus_Response())
    if parsed_response.status == api_engine.ERROR:
        raise Exception(parsed_response.error)
    print(f"Indexer output deleted.")


def delete_indexer_output_in_policy(engine_handler: EngineHandler, stop_on_warn: bool = True) -> None:
    request = api_policy.AssetDelete_Request()
    request.asset = "output/indexer/0"
    request.policy = "policy/wazuh/0"
    request.namespace = "system"
    print(f"Deleting indexer output to policy...\n{request}")
    error, response = engine_handler.api_client.send_recv(request)
    if error:
        raise Exception(error)
    parsed_response = ParseDict(response, api_policy.AssetDelete_Response())
    if parsed_response.status == api_engine.ERROR:
        raise Exception(parsed_response.error)
    if len(parsed_response.warning) > 0 and stop_on_warn:
        raise Exception(parsed_response.warning)
    print("indexer output deleted to policy.")


def decoder_health_test(env_path: Path, integration_name: Optional[str] = None, skip: Optional[List[str]] = None):
    print("Validating environment...")
    conf_path = (env_path / "engine/general.conf").resolve()
    if not conf_path.is_file():
        sys.exit(f"Configuration file not found: {conf_path}")

    bin_path = (env_path / "bin/wazuh-engine").resolve()
    if not bin_path.is_file():
        sys.exit(f"Engine binary not found: {bin_path}")

    integrations_path = (env_path / "ruleset/integrations").resolve()
    if not integrations_path.exists():
        sys.exit(f"Integrations directory not found: {integrations_path}")
    print("Environment validated.")

    schema = env_path / "ruleset/schemas/engine-schema.json"
    try:
        with open(schema, 'r') as schema_file:
            schema_data = json.load(schema_file)
            schema_fields = set(schema_data.get("fields", {}).keys())
    except Exception as e:
        sys.exit(f"Error reading the JSON schema file: {e}")

    print("Starting engine...")
    engine_handler = EngineHandler(bin_path.as_posix(), conf_path.as_posix())

    integrations: List[Path] = []
    CORE_WAZUH_DECODER_PATH = env_path / 'ruleset' / 'decoders' / 'wazuh-core' / 'core-wazuh-message.yml'

    try:
        if integration_name is not None:
            print(f"Specified integration: {integration_name}")
            integration_path = integrations_path / integration_name
            if not integration_path.exists():
                sys.exit(f"Integration {integration_name} not found.")

            integrations.append(integration_path)
        else:
            for integration_path in integrations_path.iterdir():
                if not integration_path.is_dir():
                    continue
                print(f'Discovered integration: {integration_path.name}')
                if skip and integration_path.name in skip:
                    print(f'Skipping integration: {integration_path.name}')
                    continue
                integrations.append(integration_path)

        opensearch_management.init_opensearch(env_path / 'ruleset' / 'schemas' / 'template.json')
        engine_handler.start()
        print("Engine started.")
        print("Update wazuh-core-message decoder")
        if not exist_index_output(engine_handler):
            load_indexer_output(engine_handler)
            load_indexer_output_in_policy(engine_handler)

        print("\n\nRunning tests...")
        results = run_test(integrations, engine_handler.api_socket_path, schema_fields)

    finally:
        if exist_index_output(engine_handler):
            delete_indexer_output_in_policy(engine_handler)
            delete_indexer_output(engine_handler)
        print("Restart wazuh-core-message decoder changes")
        engine_handler.stop()
        opensearch_management.stop()
        print("Engine stopped.")

    print("\n\n")
    for result in results:
        print(result)

    success = True
    for result in results:
        if not result.success:
            success = False

    if success:
        print("All tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)


def rule_health_test(env_path: Path, ruleset_name: Optional[str] = None, skip: Optional[List[str]] = None):
    print("Validating environment for rules...")
    conf_path = (env_path / "engine/general.conf").resolve()
    if not conf_path.is_file():
        sys.exit(f"Configuration file not found: {conf_path}")

    bin_path = (env_path / "bin/wazuh-engine").resolve()
    if not bin_path.is_file():
        sys.exit(f"Engine binary not found: {bin_path}")

    rules_path = (env_path / "ruleset/rules").resolve()
    if not rules_path.exists():
        sys.exit(f"Rules directory not found: {rules_path}")
    print("Environment validated.")

    schema = env_path / "ruleset/schemas/engine-schema.json"
    try:
        with open(schema, 'r') as schema_file:
            schema_data = json.load(schema_file)
            schema_fields = set(schema_data.get("fields", {}).keys())
    except Exception as e:
        sys.exit(f"Error reading the JSON schema file: {e}")

    print("Starting engine...")
    engine_handler = EngineHandler(bin_path.as_posix(), conf_path.as_posix())

    results: List[Result] = []
    rules: List[Path] = []
    CORE_WAZUH_DECODER_PATH = env_path / 'ruleset' / 'decoders' / 'wazuh-core' / 'core-wazuh-message.yml'

    try:
        if ruleset_name is not None:
            print(f"Specific ruleset: {ruleset_name}")
            ruleset_path = rules_path / ruleset_name
            if not ruleset_path.exists():
                sys.exit(f"Ruleset {ruleset_name} not found.")
            rules.append(ruleset_path)
        else:
            for ruleset_path in rules_path.iterdir():
                if not ruleset_path.is_dir():
                    continue
                print(f'Discovered ruleset: {ruleset_path.name}')
                if skip and ruleset_path.name in skip:
                    print(f'Skipping ruleset: {ruleset_path.name}')
                    continue
                rules.append(ruleset_path)

        opensearch_management.init_opensearch(env_path / 'ruleset' / 'schemas' / 'template.json')
        engine_handler.start()
        print("Engine started.")
        if not exist_index_output(engine_handler):
            load_indexer_output(engine_handler)
            load_indexer_output_in_policy(engine_handler)
        print("Update wazuh-core-message decoder")

        print("\n\nRunning tests...")
        results = run_test(rules, engine_handler.api_socket_path, schema_fields)

    finally:
        if exist_index_output(engine_handler):
            delete_indexer_output_in_policy(engine_handler)
            delete_indexer_output(engine_handler)
        print("Restart wazuh-core-message decoder changes")
        engine_handler.stop()
        opensearch_management.stop()
        print("Engine stopped.")

    print("\n\n")
    for result in results:
        print(result)

    success = True
    for result in results:
        if not result.success:
            success = False

    if success:
        print("All tests passed.")
        sys.exit(0)
    else:
        sys.exit(1)


def run(args):
    env_path = Path(args['environment'])
    integration_name = args.get('integration')
    rule_folder = args.get('rule_folder')
    target = args.get('target')
    skip = args['skip']

    provided_args = sum([bool(integration_name), bool(rule_folder), bool(target)])
    if provided_args > 1:
        sys.exit("It is only possible to specify one of the following arguments: 'target', 'integration' or 'rule_folder'")

    if rule_folder:
        return rule_health_test(env_path, rule_folder, skip)

    elif integration_name:
        return decoder_health_test(env_path, integration_name, skip)

    elif target:
        if target == 'decoder':
            return decoder_health_test(env_path, integration_name, skip)
        elif target == 'rule':
            return rule_health_test(env_path, rule_folder, skip)
        else:
            sys.exit(f"The {target} target is not currently supported")

    else:
        sys.exit("At least one of the following arguments must be specified: 'target', 'integration' or 'rule_folder'")
