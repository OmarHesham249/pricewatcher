#!/bin/bash
set -e
awslocal sqs create-queue --queue-name sarak-scrape-dlq
awslocal sqs create-queue --queue-name sarak-scrape-queue
awslocal sqs create-queue --queue-name sarak-alert-queue
echo "LocalStack SQS queues initialized."
