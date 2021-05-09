import json
import logging
import argparse
import os
from datetime import datetime, timedelta
from time import sleep

from beem import Hive
from beem.account import Account
from beem.blockchain import Blockchain

USE_TEST_NODE = os.getenv("USE_TEST_NODE", 'False').lower() in ('true', '1', 't')
WATCHED_OPERATION_IDS = ['podping','hive-hydra']
TEST_NODE = ['http://testnet.openhive.network:8091']


logging.basicConfig(level=logging.INFO,
                    format=f'%(asctime)s %(levelname)s %(name)s %(threadName)s : %(message)s')

if USE_TEST_NODE:
    hive = Hive(node=TEST_NODE)
else:
    hive = Hive()


# Argument Parser
my_parser = argparse.ArgumentParser(prog='hive-watcher',
                                    usage='%(prog)s [options]',
                                    description="PodPing - Watch the Hive Blockchain for notifications of new Podcast Episodes")

my_parser = argparse.ArgumentParser(fromfile_prefix_chars='@')

my_parser.add_argument('-s',
                       '--scan',
                       action='store', type=int, required=False,
                       default=1,
                       help='Time in hours to look back up the chain for pings')

my_parser.add_argument('-r',
                       '--reports',
                       action='store', type=int, required=False,
                       default=5,
                       help='Time in minutes between periodic status reports, use 0 for no periodic reports')


# my_parser.add_argument('-h',
#                        '--help',
#                        action='help',
#                        help='Shows Help')

def get_allowed_accounts(acc_name='podping') -> bool:
    """ get a list of all accounts allowed to post by acc_name (podping)
        and only react to these accounts """

    # Switching to a simpler authentication system. Only podpings from accounts which
    # the PODPING Hive account FOLLOWS will be watched.
    master_account = Account(acc_name, blockchain_instance=hive, lazy=True)
    allowed = master_account.get_following()
    return allowed

    # Depreciated OLD method which was silly. Will remove later
    if USE_TEST_NODE:
        return ['learn-to-code','hive-hydra','hivehydra','flyingboy','blocktvnews']

    hiveaccount = Account(acc_name, blockchain_instance=hive, lazy=True)
    try:
        allowed = hiveaccount['posting']['account_auths']
        allowed = [x for (x,_) in allowed]

    except Exception as ex:
        allowed = []

    return allowed

def allowed_op_id(operation_id):
    """ Checks if the operation_id is in the allowed list """
    if operation_id in WATCHED_OPERATION_IDS:
        return True
    else:
        return False

def send_to_socket(post, clientSocket) -> None:
    """ Take in a post and a socket and send the url to a socket """
    data = json.loads(post.get('json'))
    url = data.get('url')
    if url:
        clientSocket.send(url.encode())

    # Do we need to receive from the socket?



def output(post) -> None:
    """ Prints out the post and extracts the custom_json """
    data = json.loads(post.get('json'))
    data['required_posting_auths'] = post.get('required_posting_auths')
    data['trx_id'] = post.get('trx_id')
    data['timestamp'] = post.get('timestamp')
    if USE_TEST_NODE:
        data['test_node'] = True
    logging.info('Feed Updated - ' + str(data.get('timestamp')) + ' - ' + data.get('trx_id') + ' - ' + data.get('url'))

def output_status(timestamp, pings, count_posts, time_to_now='', current_block_num='') -> None:
    """ Writes out a status update at with some count data """
    if time_to_now:
        logging.info(f'{timestamp} PodPings: {pings} - Count: {count_posts} - Time Delta: {time_to_now}')

    else:
        logging.info(f'{timestamp} PodPings: {pings} - Count: {count_posts} - Current BlockNum: {current_block_num}')


def scan_live(report_freq = None, reports = True):
    """ watches the stream from the Hive blockchain """

    if type(report_freq) == int:
        report_freq = timedelta(minutes=report_freq)
    allowed_accounts = get_allowed_accounts()

    blockchain = Blockchain(mode="head", blockchain_instance=hive)
    current_block_num = blockchain.get_current_block_num()
    if reports:
        logging.info('Watching live from block_num: ' + str(current_block_num))

    # If you want instant confirmation, you need to instantiate
    # class:beem.blockchain.Blockchain with mode="head",
    # otherwise, the call will wait until confirmed in an irreversible block.
    stream = blockchain.stream(opNames=['custom_json'], raw_ops=False, threading=False, thread_num=4)

    start_time = datetime.utcnow()
    count_posts = 0
    pings = 0

    for post in stream:
        count_posts +=1
        time_dif = post['timestamp'].replace(tzinfo=None) - start_time
        if reports:
            if time_dif > report_freq:
                current_block_num = str(blockchain.get_current_block_num())
                timestamp = str(post['timestamp'])
                output_status(timestamp, pings, count_posts, current_block_num=current_block_num)
                start_time =post['timestamp'].replace(tzinfo=None)
                count_posts = 0
                pings = 0

        if allowed_op_id(post['id']):
            if  (set(post['required_posting_auths']) & set(allowed_accounts)):
                output(post)
                pings += 1

        if time_dif > timedelta(hours=1):
            # Refetch the allowed_accounts every hour in case we add one.
            allowed_accounts = get_allowed_accounts()

def scan_history(timed= None, report_freq = None, reports = True):
    """ Scans back in history timed time delta ago, reporting with report_freq
        if timed is an int, treat it as hours, if report_freq is int, treat as min """
    scan_start_time = datetime.utcnow()

    if not report_freq:
        report_freq = timedelta(minutes=5)

    if not timed:
        timed = timedelta(hours=1)

    if type(timed) == int:
        timed = timedelta(hours=timed)

    if type(report_freq) == int:
        report_freq = timedelta(minutes=report_freq)

    allowed_accounts = get_allowed_accounts()

    blockchain = Blockchain(mode="head", blockchain_instance=hive)
    start_time = datetime.utcnow() - timed
    count_posts = 0
    pings = 0
    block_num = blockchain.get_estimated_block_num(start_time)
    if reports:
        logging.info('Started catching up')
    stream = blockchain.stream(opNames=['custom_json'], start = block_num,
                               max_batch_size = 50,
                               raw_ops=False, threading=False)
    for post in stream:
        post_time = post['timestamp'].replace(tzinfo=None)
        time_dif = post_time - start_time
        time_to_now = datetime.utcnow() - post_time
        count_posts += 1
        if reports:
            if time_dif > report_freq:
                timestamp = str(post['timestamp'])
                output_status(timestamp, pings, count_posts, time_to_now)
                start_time =post['timestamp'].replace(tzinfo=None)
                count_posts = 0
                pings = 0

        if allowed_op_id(post['id']):
            if (set(post['required_posting_auths']) & set(allowed_accounts)):
                output(post)
                pings += 1

        if time_to_now < timedelta(seconds=2):
            logging.info('block_num: ' + str(post['block_num']))
            # Break out of the for loop we've caught up.
            break

    scan_time = datetime.utcnow() - scan_start_time
    logging.info('Finished catching up at block_num: ' + str(post['block_num']) + ' in '+ str(scan_time))


def main() -> None:
    """ Main file """
    args = my_parser.parse_args()
    myArgs = vars(args)

    """ do we want periodic reports? """
    if myArgs['reports'] == 0:
        reports = False
    else:
        reports = True
        if USE_TEST_NODE:
            logging.info('---------------> Using Test Node ' + TEST_NODE[0])
        else:
            logging.info('---------------> Using Main Hive Chain ')


    """ scan_history will look back over the last 1 hour reporting every 15 minute chunk """
    if myArgs['scan'] != 0 :
        scan_history(myArgs['scan'], 15, reports)

    """ scan_live will resume live scanning the chain and report every 5 minutes or when
        a notification arrives """
    scan_live(myArgs['reports'],reports)



if __name__ == "__main__":

    main()
