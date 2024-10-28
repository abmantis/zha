"""Test zhaws binary sensor."""

from collections.abc import Awaitable, Callable
from unittest.mock import MagicMock, call

import pytest
import zigpy.profiles.zha
from zigpy.zcl.clusters import general, measurement, security

from tests.common import (
    SIG_EP_INPUT,
    SIG_EP_OUTPUT,
    SIG_EP_PROFILE,
    SIG_EP_TYPE,
    create_mock_zigpy_device,
    get_entity,
    join_zigpy_device,
    send_attributes_report,
    update_attribute_cache,
)
from zha.application import Platform
from zha.application.gateway import Gateway
from zha.application.platforms import PlatformEntity
from zha.application.platforms.binary_sensor import (
    Accelerometer,
    BinarySensor,
    IASZone,
    IASZoneBatteryLow,
    IASZoneTamper,
    IASZoneTestMode,
    IASZoneTrouble,
    Occupancy,
)
from zha.zigbee.cluster_handlers.const import SMARTTHINGS_ACCELERATION_CLUSTER

DEVICE_IAS = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.IAS_ZONE,
        SIG_EP_INPUT: [security.IasZone.cluster_id],
        SIG_EP_OUTPUT: [],
    }
}


DEVICE_OCCUPANCY = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.OCCUPANCY_SENSOR,
        SIG_EP_INPUT: [measurement.OccupancySensing.cluster_id],
        SIG_EP_OUTPUT: [],
    }
}


DEVICE_SMARTTHINGS_MULTI = {
    1: {
        SIG_EP_PROFILE: zigpy.profiles.zha.PROFILE_ID,
        SIG_EP_TYPE: zigpy.profiles.zha.DeviceType.IAS_ZONE,
        SIG_EP_INPUT: [
            general.Basic.cluster_id,
            general.PowerConfiguration.cluster_id,
            general.Identify.cluster_id,
            general.PollControl.cluster_id,
            measurement.TemperatureMeasurement.cluster_id,
            security.IasZone.cluster_id,
            SMARTTHINGS_ACCELERATION_CLUSTER,
        ],
        SIG_EP_OUTPUT: [general.Identify.cluster_id, general.Ota.cluster_id],
    }
}


def get_binary_sensor_entity(device: dict, entity_type: type[BinarySensor]):
    """Assert that a binary sensor entity is valid."""
    entity: PlatformEntity = get_entity(
        device, Platform.BINARY_SENSOR, entity_type=entity_type
    )

    assert entity is not None
    assert isinstance(entity, entity_type)
    assert entity.PLATFORM == Platform.BINARY_SENSOR

    return entity


async def async_test_binary_sensor_occupancy(
    zha_gateway: Gateway,
    cluster: general.OnOff,
    entity: Occupancy,
    plugs: dict[str, int],
) -> None:
    """Test getting on and off messages for binary sensors."""
    # binary sensor on
    await send_attributes_report(zha_gateway, cluster, {1: 0, 0: 1, 2: 2})
    assert entity.is_on

    # binary sensor off
    await send_attributes_report(zha_gateway, cluster, {1: 1, 0: 0, 2: 2})
    assert entity.is_on is False

    # test refresh
    cluster.read_attributes.reset_mock()
    assert entity.is_on is False
    cluster.PLUGGED_ATTR_READS = plugs
    update_attribute_cache(cluster)
    await entity.async_update()
    await zha_gateway.async_block_till_done()
    assert cluster.read_attributes.await_count == 1
    assert cluster.read_attributes.await_args == call(
        ["occupancy"], allow_cache=True, only_cache=True, manufacturer=None
    )
    assert entity.is_on


@pytest.mark.parametrize(
    "device, on_off_test, cluster_name, entity_type, plugs",
    [
        (
            DEVICE_OCCUPANCY,
            async_test_binary_sensor_occupancy,
            "occupancy",
            Occupancy,
            {"occupancy": 1},
        ),
    ],
)
async def test_binary_sensor(
    zha_gateway: Gateway,
    device: dict,
    on_off_test: Callable[..., Awaitable[None]],
    cluster_name: str,
    entity_type: type,
    plugs: dict[str, int],
) -> None:
    """Test ZHA binary_sensor platform."""
    zigpy_device = create_mock_zigpy_device(zha_gateway, device)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    entity: PlatformEntity = get_binary_sensor_entity(zha_device, entity_type)
    assert entity.is_on is False

    # test getting messages that trigger and reset the sensors
    cluster = getattr(zigpy_device.endpoints[1], cluster_name)
    await on_off_test(zha_gateway, cluster, entity, plugs)


async def test_iaszone_entities(
    zha_gateway: Gateway,
) -> None:
    """Test multiple entities from IASZone."""
    zigpy_device = create_mock_zigpy_device(zha_gateway, DEVICE_IAS)
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    alarm_entity: PlatformEntity = get_binary_sensor_entity(
        zha_device, entity_type=IASZone
    )
    tamper_entity: PlatformEntity = get_binary_sensor_entity(
        zha_device, entity_type=IASZoneTamper
    )
    batterylow_entity: PlatformEntity = get_binary_sensor_entity(
        zha_device, entity_type=IASZoneBatteryLow
    )
    trouble_entity: PlatformEntity = get_binary_sensor_entity(
        zha_device, entity_type=IASZoneTrouble
    )
    testmode_entity: PlatformEntity = get_binary_sensor_entity(
        zha_device, entity_type=IASZoneTestMode
    )
    assert alarm_entity.is_on is False
    assert tamper_entity.is_on is False
    assert batterylow_entity.is_on is False
    assert trouble_entity.is_on is False
    assert testmode_entity.is_on is False

    cluster = getattr(zigpy_device.endpoints[1], "ias_zone")

    # alarm sensor on from bit 0
    cluster.listener_event("cluster_command", 1, 0, [0b0000000001])
    await zha_gateway.async_block_till_done()
    assert alarm_entity.is_on
    assert tamper_entity.is_on is False
    assert batterylow_entity.is_on is False
    assert trouble_entity.is_on is False
    assert testmode_entity.is_on is False

    # alarm sensor on from bit 1
    cluster.listener_event("cluster_command", 1, 0, [0b0000000010])
    await zha_gateway.async_block_till_done()
    assert alarm_entity.is_on
    assert tamper_entity.is_on is False
    assert batterylow_entity.is_on is False
    assert trouble_entity.is_on is False
    assert testmode_entity.is_on is False

    # tamper bit
    cluster.listener_event("cluster_command", 1, 0, [0b0000000100])
    await zha_gateway.async_block_till_done()
    assert alarm_entity.is_on is False
    assert tamper_entity.is_on
    assert batterylow_entity.is_on is False
    assert trouble_entity.is_on is False
    assert testmode_entity.is_on is False

    # battery bit
    cluster.listener_event("cluster_command", 1, 0, [0b0000001000])
    await zha_gateway.async_block_till_done()
    assert alarm_entity.is_on is False
    assert tamper_entity.is_on is False
    assert batterylow_entity.is_on
    assert trouble_entity.is_on is False
    assert testmode_entity.is_on is False

    # battery defect bit
    cluster.listener_event("cluster_command", 1, 0, [0b1000000000])
    await zha_gateway.async_block_till_done()
    assert alarm_entity.is_on is False
    assert tamper_entity.is_on is False
    assert batterylow_entity.is_on
    assert trouble_entity.is_on is False
    assert testmode_entity.is_on is False

    # trouble bit
    cluster.listener_event("cluster_command", 1, 0, [0b0001000000])
    await zha_gateway.async_block_till_done()
    assert alarm_entity.is_on is False
    assert tamper_entity.is_on is False
    assert batterylow_entity.is_on is False
    assert trouble_entity.is_on
    assert testmode_entity.is_on is False

    # test mode bit
    cluster.listener_event("cluster_command", 1, 0, [0b0100000000])
    await zha_gateway.async_block_till_done()
    assert alarm_entity.is_on is False
    assert tamper_entity.is_on is False
    assert batterylow_entity.is_on is False
    assert trouble_entity.is_on is False
    assert testmode_entity.is_on

    # all sensors off
    cluster.listener_event("cluster_command", 1, 0, [0b0000000000])
    await zha_gateway.async_block_till_done()
    assert alarm_entity.is_on is False
    assert tamper_entity.is_on is False
    assert batterylow_entity.is_on is False
    assert trouble_entity.is_on is False
    assert testmode_entity.is_on is False

    # test refresh
    cluster.read_attributes.reset_mock()
    assert alarm_entity.is_on is False
    assert tamper_entity.is_on is False
    assert batterylow_entity.is_on is False
    assert trouble_entity.is_on is False
    assert testmode_entity.is_on is False
    cluster.PLUGGED_ATTR_READS = {"zone_status": 0b1111111111}
    update_attribute_cache(cluster)
    await alarm_entity.async_update()
    await zha_gateway.async_block_till_done()
    assert cluster.read_attributes.await_count == 1
    assert cluster.read_attributes.await_args == call(
        ["zone_status"], allow_cache=False, only_cache=False, manufacturer=None
    )
    assert alarm_entity.is_on
    assert tamper_entity.is_on
    assert batterylow_entity.is_on
    assert trouble_entity.is_on
    assert testmode_entity.is_on


async def test_smarttthings_multi(
    zha_gateway: Gateway,
) -> None:
    """Test smartthings multi."""
    zigpy_device = create_mock_zigpy_device(
        zha_gateway, DEVICE_SMARTTHINGS_MULTI, manufacturer="Samjin", model="multi"
    )
    zha_device = await join_zigpy_device(zha_gateway, zigpy_device)

    entity: PlatformEntity = get_binary_sensor_entity(
        zha_device, entity_type=Accelerometer
    )
    assert entity.is_on is False

    st_ch = zha_device.endpoints[1].all_cluster_handlers["1:0xfc02"]
    assert st_ch is not None

    st_ch.emit_zha_event = MagicMock(wraps=st_ch.emit_zha_event)

    await send_attributes_report(zha_gateway, st_ch.cluster, {0x0012: 120})

    assert st_ch.emit_zha_event.call_count == 1
    assert st_ch.emit_zha_event.mock_calls == [
        call(
            "attribute_updated",
            {"attribute_id": 18, "attribute_name": "x_axis", "attribute_value": 120},
        )
    ]
