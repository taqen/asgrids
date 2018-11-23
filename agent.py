from abc import abstractmethod
import hashlib
import simpy
from async_communication import AsyncCommunication
from defs import Packet, Allocation, EventId
import logging
logger = logging.getLogger('Agent')
logger.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch = logging.StreamHandler()
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)
logger.addHandler(ch)
# A generic Network Agent.
class Agent():
    def __init__(self, env=None):
        """ Make sure a simulation environment is present and Agent is running.

        :param env: a simpy simulation environment
        """
        self.logger = logging.getLogger('Agent')

        self.env = simpy.rt.RealtimeEnvironment(strict=True) if env is None else env
        self.timeouts = {}
        self.running = self.env.process(self._run())

    def run(self):
        self.logger.info("started agent's infinite loop")
        if isinstance(self.env, simpy.RealtimeEnvironment):
            self.env.sync()
        try:
            self.env.run(until=self.running)
        except (KeyboardInterrupt, simpy.Interrupt) as e:
            #if not self.running.processed:
            #    self.running.interrupt()
            self.logger.debug("{}".format(e))
            self.stop()

    def _run(self):
        while True:
            try:
                yield self.env.timeout(1e-2)
            except simpy.Interrupt:
                self.logger.info("Agent._run interrupted")
                break

    def schedule(self, action, args=None, time=0, value=None):
        """ The agent's schedule function

        :param time: relative time from present to execute action
        :param action: the handle to the function to be executed at time.
        :returns:
        :rtype:

        """
        self.logger.debug("scheduling action {}".format(action))
        return self.env.process(
            self.process(action=action, args=args, time=time, value=value))

    def process(self, action, args, time=0, value=None):
        try:
            value = yield self.env.timeout(time, value=value)
        except simpy.Interrupt:
            self.logger.debug("interrupted action {}".format(action))
            return

        self.logger.debug("executing action {} after {} seconds".format(action, time))
        if args is None:
            action()
        else:
            action(**args)
        return value

    def stop(self):
        """ stop the Agent.
        Behavior left for child classes

        :returns:
        :rtype:

        """

        self.logger.debug("interrupting pending timeouts")
        for _,v in self.timeouts.items():
            if not v.processed and not v.triggered:
                v.interrupt()
        if len(self.timeouts) > 0:
            self.logger.info("remained {} timeouts not interrupted".format(len(self.timeouts)))
        self.running.interrupt()

    def create_timer(self, timeout, eid, msg=''):
        self.logger.debug("creating timer {}".format(eid))
        event = self.env.event()
        event.callbacks.append(
            lambda event: self.logger.info("timeout expired\n {}".format(msg)))
        event.callbacks.append(
            lambda event: self.cancel_timer(eid))
        event_process = self.schedule(
            action=lambda event: event.succeed(eid),
            args={'event': event},
            time=timeout)
        return event_process

    def cancel_timer(self, eid):
        self.logger.debug("canceling timer {}".format(eid))
        e = self.timeouts.pop(eid, None)
        if e is None:
            self.logger.info("no eid %s"%eid)
        if e is not None and not (e.processed or e.triggered):
            e.interrupt()
