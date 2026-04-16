# Things Remaining

## 1. Support for hifiasm, verkko, metaspades (if not included in spades), liftoff, comparative annotation toolkit (CAT), BUSCO, merqury (if needed) are should also be added.

## 2. Small ml model to predict time and price of pipelines with different length of data,tool should be trained. 

## 3. Contact, About, Help Tutorial. Their content should come from a config file.

## 4. Delete Account

## 4. 2FA Email authentication during register. Add a library that can send emails. Also add forgot password page. Change password in edit profile should have its own confirm changes button and should ask the new password twice and compare them.

## 5. Forum page might be good

## 6. Add meryl for merqury

## 7. Make it work on EC2

# Current Issues

## it waits files to be uploaded to notify the system that a pratition is filled. It should immediately change the number of available partition in the vm and the remaining number of jobs user can run at the same time. 

## If user hits the limit, it should immediately fail, not stay in pending

## Ready templates should be always available in community page

## move vm_partitions.json to /config