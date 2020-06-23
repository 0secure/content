import demistomock as demisto
from CommonServerPython import *
from CommonServerUserPython import *

from typing import Any, Tuple

""" CONSTANT VARIABLES """


CONTEXT_PREFIX = "TAXII2"

""" HELPER FUNCTIONS """


def try_parse_integer(
    int_to_parse: Any, err_msg: str = "Please provide a valid limit (positive integer)"
) -> int:
    """
    Tries to parse an integer, and if fails will throw DemistoException with given err_msg
    """
    try:
        res = int(int_to_parse)
    except (TypeError, ValueError):
        raise DemistoException(err_msg)
    return res


""" COMMAND FUNCTIONS """


def module_test_command(client):
    if client.collections:
        demisto.results("ok")
    else:
        return_error("Could not connect to server")


def fetch_indicators_command(client, initial_interval, limit, last_run_ctx) -> Tuple[list, dict]:
    """
    Fetch indicators from TAXII 2 server
    :param client: Taxii2FeedClient
    :param initial_interval: initial interval in parse_date_range format
    :param limit: upper limit of indicators to fetch
    :param last_run_ctx: last run dict with {collection_id: last_run_time string}
    :return: indicators in cortex TIM format
    """
    initial_interval, _ = parse_date_range(initial_interval, date_format=TAXII_TIME_FORMAT)
    if client.collection_to_fetch is None:
        # fetch all collections
        if client.collections is None:
            raise DemistoException(ERR_NO_COLL)
        indicators: list = []
        for collection in client.collections:
            client.collection_to_fetch = collection
            added_after = last_run_ctx[collection.id] if collection.id in last_run_ctx else initial_interval
            fetched_iocs = client.build_iterator(limit, added_after)
            indicators.extend(fetched_iocs)
            if limit >= 0:
                limit -= len(fetched_iocs)
                if limit <= 0:
                    break
            last_run_ctx[collection.id] = client.latest_fetched_indicator_created
    else:
        added_after = last_run_ctx[client.collection_to_fetch.id] \
            if client.collection_to_fetch.id in last_run_ctx \
            else initial_interval
        indicators = client.build_iterator(limit, added_after)
        # in case no indicator was fetched
        last_run_ctx[client.collection_to_fetch.id] = client.latest_fetched_indicator_created \
            if client.latest_fetched_indicator_created \
            else added_after
    return indicators, last_run_ctx


def get_indicators_command(client, raw="false", limit=10, added_after=None):
    """
    Fetch indicators from TAXII 2 server
    :param client: Taxii2FeedClient
    :param raw: When set to "true" will return only rawJSON
    :param limit: upper limit of indicators to fetch
    :param (Optional) added_after: added after time string in parse_date_range format
    :return: indicators in cortex TIM format
    """
    limit = try_parse_integer(limit)
    if added_after:
        added_after, _ = parse_date_range(added_after, date_format=TAXII_TIME_FORMAT)
    raw = raw == "true"

    if client.collection_to_fetch is None:
        # fetch all collections
        if client.collections is None:
            raise DemistoException(ERR_NO_COLL)
        indicators: list = []
        for collection in client.collections:
            client.collection_to_fetch = collection
            fetched_iocs = client.build_iterator(limit, added_after)
            indicators.extend(fetched_iocs)
            if limit >= 0:
                limit -= len(fetched_iocs)
                if limit <= 0:
                    break

    else:
        indicators = client.build_iterator(limit=limit, added_after=added_after)

    if raw:
        demisto.results({"indicators": [x.get("rawJSON") for x in indicators]})
        return

    md = f"Found {len(indicators)} results:\n" + tableToMarkdown(
        "", indicators, ["value", "type"]
    )
    if indicators:
        return CommandResults(
            outputs_prefix=CONTEXT_PREFIX + ".Indicators",
            outputs_key_field="value",
            outputs=indicators,
            readable_output=md,
        )
    return md


def get_collections_command(client):
    """
    Get the available collections in the TAXII server
    :param client: FeedClient
    :return: available collections
    """
    collections = list()
    for collection in client.collections:
        collections.append({"Name": collection.title, "ID": collection.id})
    md = tableToMarkdown("TAXII2 Server Collections:", collections, ["Name", "ID"])
    return CommandResults(
        outputs_prefix=CONTEXT_PREFIX + ".Collections",
        outputs_key_field="ID",
        outputs=collections,
        readable_output=md,
    )


def reset_fetch_command(client):
    """
    Reset the last fetch from the integration context
    """
    demisto.setIntegrationContext({})
    return (
        "Fetch was reset successfully. Your next indicator fetch will collect indicators from "
        'the configured "First Fetch Time"'
    )


def main():
    params = demisto.params()
    args = demisto.args()
    url = params.get("url")
    collection_to_fetch = params.get("collection_to_fetch")
    credentials = params.get("credentials") or {}
    username = credentials.get("identifier")
    password = credentials.get("password")
    proxies = handle_proxy()
    verify_certificate = not params.get("insecure", False)

    command = demisto.command()
    demisto.info(f"Command being called in {CONTEXT_PREFIX} is {command}")

    try:
        client = Taxii2FeedClient(
            url, collection_to_fetch, proxies, verify_certificate, username, password
        )
        client.initialise()
        commands = {
            "taxii2-reset-fetch-indicators": reset_fetch_command,
            "taxii2-get-indicators": get_indicators_command,
            "taxii2-get-collections": get_collections_command,
        }

        if demisto.command() == "test-module":
            # This is the call made when pressing the integration Test button.
            module_test_command(client)

        elif demisto.command() == "fetch-indicators":
            initial_interval = params.get("initial_interval")
            limit = try_parse_integer(params.get("limit") or -1)
            integration_ctx = demisto.getIntegrationContext() or {}
            (indicators, integration_ctx) = fetch_indicators_command(
                client, initial_interval, limit, integration_ctx
            )
            for iter_ in batch(indicators, batch_size=2000):
                demisto.createIndicators(iter_)

            demisto.setIntegrationContext(integration_ctx)
        else:
            return_results(commands[command](client, **args))  # type: ignore[operator]

    except Exception as e:
        err_msg = f"Failed to execute {command} command. Error: {str(e)}\n\ntraceback: {traceback.format_exc()}"
        if isinstance(e, requests.exceptions.SSLError):
            LOG(err_msg)
            err_msg = (
                "Encountered an HTTPS certificate error. This error can be ignored by enabling "
                '"Trust any certificate (not secure)" in the instance configuration.'
            )
        return_error(err_msg)


# from Packs.ApiModules.Scripts.TAXII2ApiModule.TAXII2ApiModule import *  # noqa: E402
from TAXII2ApiModule import *  # noqa: E402

if __name__ in ("__main__", "__builtin__", "builtins"):
    main()
