#!/bin/bash

work_dir=$(cd $(dirname $0)/..;pwd)
cd $work_dir

. ./.venv/bin/activate

echo 投稿 $1
python $work_dir/post.py $1
