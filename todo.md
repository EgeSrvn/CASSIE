# Things Remaining

## CHECK WHETHER ALL THE TOOLS IN THE APP IS WORKING CORRECTLY

## 2. Small ml model to predict time and price of pipelines with different length of data,tool should be trained. 

## 6. Add meryl for merqury

## 7. Make it work on EC2

## Create a comprehensive setup readme file

## MAKE THE CODEBASE SIMPLER; REMOVE ANY REDUNDANCY; SOLVE ANY ISSUES RESULTED BY THIS SIMPLIFICATION.

# Current Issues

##  It should immediately change the remaining number of jobs user can run at the same time. 

## If user hits the limit, it should immediately fail, not stay in pending

## move vm_partitions.json to /config

## in job details, blocks in execution training, and pipeline input requirements, view file window are still white.In job configuration, vm selection, and intent-based pipeline, tool details are still white. there is a box around some building blocks in pipeline builder. 

## For some reason, configure job or use pipeline refreshes constantly and this causes selected vm to be changed constantly. 

## Price/time estimations in job submit page should be at the bottom with the submit job button in both use from pipeline and configure job. 

## Final pipeline should always be visible and dynamic in a box just under the tools checkboxes without a need of refreshing the page in configure job and use from pipeline page. 

## There should be extendable close-open sections (arrow at right) that will seperate building blocks in pipeline builder by input blocks, utility blocks(resulti checkpoint), and one for each job type (assembly, qulity control, etc.). Also, in pipeline builder, I should be able to rename the block names, so that input blocks can be more identifiable for later uploading inputs. Also, results should be named as (result_block_name_tool).(output_file_format).

## For some reason, while configuring a job, if i select use uploaded file instead of intermediate output, it generates an input block even though I already put it as an input for another block. Solve this by creating an input block per each uploaded input and can be able to change the name of these blocks, and let me select the input for the tools by selecting these input blocks not the uploaded inputs direclty.

## !!!!!!!!!!!!! ADD THE LAST DETAILED DESIGN DOCUMENT TO CASSIE WEB PAGE !!!!!!!!!!!!!

## !!!!!!!!!!!!! EITHER GET ACCESS TO OSMAN'S CASSIE WEB PAGE AND CHANGE IT WITH THE EMRE'S OR MAKE THE WEB PAGE IN THE PROJECT PAGE CHANGE THE LISTED WEB PAGE !!!!!!!!!!!!!

## Make the tool selection, input upload, tool configuration, seein the final pipeline and submitting it level by level. First select tools, select pipeline, or slect intent based pipeline / upload inputs and possibly rename input blocks / configure tools and priorities / see the finl pipeline, estimated time and price and submit the job.

## make 2fa and notfications optional, select these from profile

## start recording flops per opertaion / input size / input for model training

## active system resource use in job details

## job details also should be leveled and not everything should be shown in the same page

## make the auto cencor better in forum and community, and add a report button, the admin panel should have a subpage to see reported contents.

## add downvote and upvote for forum and community elements. 