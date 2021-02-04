#!/usr/bin/env python3
# Copyright 2021 Felipe
# See LICENSE file for licensing details.

"""Charm the service."""

import datetime
import logging
import os
import subprocess

from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, EventSource, StoredState
from ops.main import main
from ops.model import (
    ActiveStatus,
    ModelError,
    WaitingStatus,
)
from pathlib import Path

logger = logging.getLogger(__name__)


class AthenaCoreDataVolumeReady(EventBase):
    pass


class AthenaCoreMonitorCharmEvents(CharmEvents):
    data_volume_ready = EventSource(AthenaCoreDataVolumeReady)


class CharmAthenaMonitorCharm(CharmBase):
    on = AthenaCoreMonitorCharmEvents()
    _stored = StoredState()

    MONITOR_SERVICE = 'snap.athena-core.monitor.service'
    SNAPS = ['athena-core']
    SNAP_COMMON_PATH = '/var/snap/athena-core/common'
    MONITOR_CONFIG_PATH = os.path.join(SNAP_COMMON_PATH, 'athena-monitor.yaml')
    DATA_LOCATION = '/var/snap/athena-core/common/data'

    def __init__(self, *args):
        super().__init__(*args)
        self.framework.observe(self.on.config_changed,
                               self.on_config_changed)
        self.framework.observe(self.on.install,
                               self.on_install)
        self.framework.observe(self.on.data_storage_attached,
                               self.on_data_storage_attached)
        self.framework.observe(self.on.update_status,
                               self.on_update_status)
        self._stored.set_default(
            config_content="",
            data_volume_available=False
        )

    def on_config_changed(self, _):
        current = self.config["config-content"]
        if current == self._stored.config_content:
            logger.debug("Configuration hasn't changed. Doing nothing")
            return

        logger.debug(f"Writing new config file to {self.MONITOR_CONFIG_PATH}")
        with open(self.MONITOR_CONFIG_PATH, 'w') as f:
            f.write(current)
            f.flush()
            self._stored.config_content = current

        if self._stored.data_volume_available:
            logging.debug(f"Restarting {self.MONITOR_SERVICE}")
            subprocess.check_call(['systemctl', 'restart',
                                   self.MONITOR_SERVICE])

    def on_install(self, event):
        try:
            core_res = self.model.resources.fetch('core')
        except ModelError:
            core_res = None
        try:
            athena_core_res = self.model.resources.fetch('athena-core')
        except ModelError:
            athena_core_res = None

        cmd = ['snap', 'install']
        # Install the snaps from a resource if provided. Alternatively, snapd
        # will attempt to download it automatically.
        if core_res is not None and Path(core_res).stat().st_size:
            logging.debug("Installing core snap from the resource attached")
            subprocess.check_call(cmd + ['--dangerous', core_res])

        athena_core_cmd = cmd
        if athena_core_res is not None \
           and Path(athena_core_res).stat().st_size:
            athena_core_cmd += ['--dangerous', athena_core_res]
        else:
            channel = self.model.config['snap-channel']
            athena_core_cmd += ['--channel', channel] + self.SNAPS

        logging.debug(f"Installing snaps: {athena_core_cmd}")
        subprocess.check_call(athena_core_cmd)

    def on_data_storage_attached(self, event):
        with open(os.path.join(self.DATA_LOCATION, '.touched'), 'w') as f:
            f.write("%s\n" % datetime.datetime.now())
            f.flush()

        self._stored.data_volume_available = True
        self.on.config_changed.emit()

    def on_data_storage_detaching(self, event):
        self._stored.data_volume_available = False
        logging.debug("Stopping athena-core.monitor")
        subprocess.check_call(['systemctl', 'stop', self.MONITOR_SERVICE])
        self.on.config_changed.emit()

    def on_update_status(self, event):
        try:
            subprocess.check_call(['systemctl', 'status',
                                   self.MONITOR_SERVICE])
            self.model.unit.status = \
                ActiveStatus(f"{self.MONITOR_SERVICE} is running")
        except subprocess.CalledProcessError as ex:
            logging.debug("%s" % ex)
            self.model.unit.status = \
                WaitingStatus(f"{self.MONITOR_SERVICE} is not running")


if __name__ == "__main__":
    main(CharmAthenaMonitorCharm)
