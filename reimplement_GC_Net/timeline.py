# Copyright 2015 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

"""
Obtain timeline analysis for GC-Net.
To know which part makes it slow when running on CPU.
It is much faster when running on GPU(s).

"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from datetime import datetime
import math
import time
import os
import numpy as np
import tensorflow as tf

import gcnet_model
import image_processing
from SceneFlow_data import SceneFlowData
from tensorflow.python.client import timeline
#from tensorflow.python import debug as tf_debug

FLAGS = tf.app.flags.FLAGS
BATCH_SIZE = 1

#tf.app.flags.DEFINE_string('dataset', 'SceneFlow', '')
tf.app.flags.DEFINE_string('mode', 'eval', 'mode')
tf.app.flags.DEFINE_boolean('debug', False,
              """Whether to show verbose summaries.""")
tf.app.flags.DEFINE_string('log_root', '/home/laoreja/tf/log/gcnet_multi_gpu_2',
                           """Directory where to write event logs' parent.""")
tf.app.flags.DEFINE_string('checkpoint_dir', '/home/laoreja/tf/log/gcnet_multi_gpu_2/train',
                           """Directory where to read model checkpoints.""")
tf.app.flags.DEFINE_integer('eval_interval_secs', 60 * 5,
                            """How often to run the eval.""")
tf.app.flags.DEFINE_boolean('run_once', True,
                         """Whether to run eval only once.""")


def eval_once(saver, summary_writer, abs_loss, total_loss, summary_op):
  """Run Eval once.

  Args:
    saver: Saver.
    summary_writer: Summary writer.
    abs_loss, total_loss: two loss ops.
    summary_op: Summary op.
  """
  with tf.Session(config=tf.ConfigProto(allow_soft_placement = True)) as sess:
    ckpt = tf.train.get_checkpoint_state(FLAGS.checkpoint_dir)
    if ckpt and ckpt.model_checkpoint_path:
      # Restores from checkpoint
      saver.restore(sess, ckpt.model_checkpoint_path)
      # Assuming model_checkpoint_path looks something like:
      #   /my-favorite-path/cifar10_train/model.ckpt-0,
      # extract global_step from it.
      tf.logging.info("ckpt.model_checkpoint_path: {}".format(ckpt.model_checkpoint_path))
      global_step = ckpt.model_checkpoint_path.split('/')[-1].split('-')[-1]
    else:
      print('No checkpoint file found')
      return
    
     
    tf.train.start_queue_runners(sess=sess)
    print('starts!')

    num_iter = 1#int(math.ceil(NUM_EVAL_SAMPLES / BATCH_SIZE))
    avg_abs_loss = 0.0
    avg_total_loss = 0.0
    step = 0
    while step < num_iter and not coord.should_stop():
      run_options = tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE)
      run_metadata = tf.RunMetadata()
      got_abs_loss, got_total_loss = sess.run([abs_loss, total_loss], options=run_options, run_metadata=run_metadata)
      
      # Create the Timeline object, and write it to a json
      tl = timeline.Timeline(run_metadata.step_stats)
      ctf = tl.generate_chrome_trace_format()
      with open('timeline.json', 'w') as f:
        f.write(ctf)

      
      avg_abs_loss += got_abs_loss
      avg_total_loss += got_total_loss
      step += 1

    avg_abs_loss /= num_iter
    avg_total_loss /= num_iter
    print('%s: avg abs, total losses = %f, %f' % (datetime.now(), avg_abs_loss, avg_total_loss))

    summary = tf.Summary()
    summary.ParseFromString(sess.run(summary_op))
    summary.value.add(tag='avg_abs_loss', simple_value=avg_abs_loss)
    summary.value.add(tag='avg_total_loss', simple_value=avg_total_loss)
    summary_writer.add_summary(summary, global_step)


def evaluate(hps, dataset):
  """Eval CIFAR-10 for a number of steps."""
  with tf.Graph().as_default() as g:
    # Get images and labels for CIFAR-10.
    num_preprocess_threads = FLAGS.num_preprocess_threads
    left_images, right_images, disparitys, masks = image_processing.inputs(
                dataset,
                batch_size = hps.batch_size,
                num_preprocess_threads=num_preprocess_threads)

    # Build a Graph that computes the logits predictions from the
    # inference model.
    model = gcnet_model.GCNet(hps, left_images, right_images, disparitys, masks, 'eval') # 
    model.build_graph_to_loss()

    # Restore the moving average version of the learned variables for eval.
    variable_averages = tf.train.ExponentialMovingAverage(
        gcnet_model.MOVING_AVERAGE_DECAY)
    variables_to_restore = variable_averages.variables_to_restore()
    saver = tf.train.Saver(variables_to_restore)

    # Build the summary operation based on the TF collection of Summaries.
    summary_op = tf.summary.merge_all()
    summary_writer = tf.summary.FileWriter(FLAGS.eval_dir, g)

    while True:
      eval_once(saver, summary_writer, model.abs_loss, model.total_loss, summary_op)
      if FLAGS.run_once:
        break
      time.sleep(FLAGS.eval_interval_secs)


def main(argv=None):  # pylint: disable=unused-argument
  dataset = SceneFlowData('debug')
  assert dataset.data_files()
  global NUM_EVAL_SAMPLES
  NUM_EVAL_SAMPLES = dataset.num_examples_per_epoch()
  
  FLAGS.eval_dir = os.path.join(FLAGS.log_root, 'eval')

  hps = gcnet_model.HParams(batch_size=BATCH_SIZE,
                             lrn_rate=0.001,
                             weight_decay_rate=0.0002,
                             relu_leakiness=0.1,
                             optimizer='RMSProp',
                             max_disparity=192) 

  evaluate(hps, dataset)


if __name__ == '__main__':
  tf.logging.set_verbosity(tf.logging.DEBUG)    
  tf.app.run()
