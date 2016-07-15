from elastalert.ruletypes import RuleType
from elastalert.elastalert import ElastAlerter
from datetime import datetime, timedelta
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ElasticsearchException
import yaml
import os
import logging

logging.basicConfig()
elastalert_logger = logging.getLogger('elastalert')

class TrafficComparation(RuleType):

    # By setting required_options to a set of strings
    # You can ensure that the rule config file specifies all
    # of the options. Otherwise, ElastAlert will throw an exception
    # when trying to load the rule.
    required_options = set(['deviation', 'distance'])

    def __init__(self, rules, args=None):
        super(TrafficComparation, self).__init__(rules, args)

        if os.path.isfile('../config.yaml'):
            filename = '../config.yaml'
        elif os.path.isfile('config.yaml'):
            filename = 'config.yaml'
        else:
            filename = ''

        if filename:
            with open(filename) as config_file:
                data = yaml.load(config_file)
            host = data.get('es_host')
            port = data.get('es_port')
            username = data.get('es_username')
            password = data.get('es_password')
            self.buffer_time = data.get('buffer_time')

            if username and password:
                connection_string = 'http://%s:%s@%s:%s/' % (username, password, host, port)
            else:
                connection_string = 'http://@%s:%s/' % (host, port)

        self.es = Elasticsearch([
            connection_string
        ])

    @staticmethod
    def create_log_message(data):
        return "Hits changed %0.4f%%. Current hits %d, last hits %d (%s - %s)" % (
            data['changed_percentage'] * 100,
            data['current_hits'],
            data['last_hits'],
            data['last_hits_start_time'],
            data['last_hits_end_time']
        )

    def add_count_data(self, data):
        (ts, current_hits), = data.items()

        delay = self.rules['query_delay']
        if delay:
            last_hits_end_time = datetime.now() - timedelta(**self.rules['distance']) - delay
        else:
            last_hits_end_time = datetime.now() - timedelta(**self.rules['distance'])

        last_hits_start_time = last_hits_end_time - timedelta(**self.buffer_time)

        query = ElastAlerter.get_query(self.rules['filter'], last_hits_start_time, last_hits_end_time)

        try:
            res = self.es.count(index=self.rules['index'], doc_type=self.rules['doc_type'], body=query, ignore_unavailable=True)
        except ElasticsearchException as e:
            # Elasticsearch sometimes gives us GIGANTIC error messages
            # (so big that they will fill the entire terminal buffer)
            if len(str(e)) > 1024:
                e = str(e)[:1024] + '... (%d characters removed)' % (len(str(e)) - 1024)
            print 'Error running count query: %s' % (e)
            return None

        # Get count number and convert to float
        last_hits = res['count'] * 1.0

        if last_hits > 0:
            changed_percentage = ((current_hits - last_hits) / current_hits)
        else:
            changed_percentage = 0

        event = {
            'last_hits': last_hits,
            'current_hits': current_hits,
            'changed_percentage': changed_percentage,
            'last_hits_start_time': last_hits_start_time,
            'last_hits_end_time': last_hits_end_time,
            '@timestamp': ts
        }

        elastalert_logger.info(TrafficComparation.create_log_message(event))

        if self.rules['negative_growth']:
            if changed_percentage < self.rules['deviation']:
                self.add_match(event)
        else:
            if changed_percentage > self.rules['deviation']:
                self.add_match(event)

    # The results of get_match_str will appear in the alert text
    def get_match_str(self, match):
        return TrafficComparation.create_log_message(match)
