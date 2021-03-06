# Copyright 2016 The TensorFlow Authors. All Rights Reserved.
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
GC-Net Train module.
Using multiple GPUs.
"""
import time
import six
import sys, os
from datetime import datetime
import re

import stereo_input
import numpy as np
import tensorflow as tf

import gcnet_model
import image_processing_KITTI
from KITTI_data import KITTIData
#import image_processing
#from SceneFlow_data import SceneFlowData

BATCH_SIZE = 1
RMSPROP_DECAY = 0.9                # Decay term for RMSProp.
RMSPROP_MOMENTUM = 0.0             # Momentum in RMSProp.
RMSPROP_EPSILON = 0.0001             # Epsilon term for RMSProp.

FLAGS = tf.app.flags.FLAGS
#tf.app.flags.DEFINE_string('dataset', 'SceneFlow', '')
tf.app.flags.DEFINE_string('log_root', '/home/laoreja/tf/log/kitti_from_retrain_6_resume',
                           'Directory to keep the checkpoints. Should be a '
                           'parent directory of FLAGS.train_dir/eval_dir.')
tf.app.flags.DEFINE_integer('num_gpus', 3,
                            'Number of gpus used for training. (0 or 1)')
tf.app.flags.DEFINE_integer('max_steps', 150000, 'max steps for training')                            
tf.app.flags.DEFINE_boolean('log_device_placement', False,
              """Whether to log device placement.""")
tf.app.flags.DEFINE_string('mode', 'resume', 'train, resume, retrain')
tf.app.flags.DEFINE_boolean('debug', True,
              """Whether to show verbose summaries.""")
tf.app.flags.DEFINE_string('ckpt_path', '/home/laoreja/tf/log/kitti_from_retrain_6/train', "path of ckpt for resume training")              

#os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3' 
# will supress verbose log info
# but cannot see print!

def tower_loss(scope, hps, dataset):
  """Calculate the total loss on a single tower running the GC-Net model.

  Args:
    scope: unique prefix string identifying the GC-Net tower, e.g. 'tower_0'
    hps: hyper parameters to pass into the model
  Returns:
     Tensor of shape [] containing the total loss for a batch of data
  """
  # Get inputs.
  num_preprocess_threads = FLAGS.num_preprocess_threads
  left_images, right_images, disparitys, masks = image_processing_KITTI.distorted_inputs(
                  dataset,
                  batch_size = hps.batch_size,
                  num_preprocess_threads=num_preprocess_threads)

  # Build inference Graph.
  model = gcnet_model.GCNet(hps, left_images, right_images, disparitys, masks, 'train') 
  model.build_graph_to_loss()
  
#  summary_name = ['abs_loss', 'total_loss']
#  for l in [model.abs_loss, model.total_loss]:
  loss_name = re.sub('%s_[0-9]*/' % gcnet_model.TOWER_NAME, '', model.abs_loss.op.name+'_abs')
  tf.summary.scalar(loss_name, model.abs_loss)
  loss_name = re.sub('%s_[0-9]*/' % gcnet_model.TOWER_NAME, '', model.total_loss.op.name+'_total')
  tf.summary.scalar(loss_name, model.total_loss)
  
  return model.total_loss, model.variables_to_restore, model.summaries#, model.debug_op_list
  
def average_gradients(tower_grads):
  """Calculate the average gradient for each shared variable across all towers.

  Note that this function provides a synchronization point across all towers.

  Args:
    tower_grads: List of lists of (gradient, variable) tuples. The outer list
      is over individual gradients. The inner list is over the gradient
      calculation for each tower.
  Returns:
     List of pairs of (gradient, variable) where the gradient has been averaged
     across all towers.
  """
  average_grads = []
  for grad_and_vars in zip(*tower_grads):
    # Note that each grad_and_vars looks like the following:
    #   ((grad0_gpu0, var0_gpu0), ... , (grad0_gpuN, var0_gpuN))
    grads = []
    for g, _ in grad_and_vars:
      # Add 0 dimension to the gradients to represent the tower.
      expanded_g = tf.expand_dims(g, 0)

      # Append on a 'tower' dimension which we will average over below.
      grads.append(expanded_g)

    # Average over the 'tower' dimension.
    grad = tf.concat(axis=0, values=grads)
    grad = tf.reduce_mean(grad, 0)

    # Keep in mind that the Variables are redundant because they are shared
    # across towers. So .. we will just return the first tower's pointer to
    # the Variable.
    v = grad_and_vars[0][1]
    grad_and_var = (grad, v)
    average_grads.append(grad_and_var)
  return average_grads  
  
def train(hps, dataset):
  """Training loop."""
  with tf.Graph().as_default(), tf.device('/cpu:0'):
    # Create a variable to count the number of train() calls. This equals the
    # number of batches processed * FLAGS.num_gpus.
    global_step = tf.get_variable(
      'global_step', [],
      initializer=tf.constant_initializer(0), trainable=False)
      
    lrn_rate = tf.constant(hps.lrn_rate, tf.float32)
    
    if hps.optimizer == 'sgd':
      opt = tf.train.GradientDescentOptimizer(lrn_rate)
    elif hps.optimizer == 'mom':
      opt = tf.train.MomentumOptimizer(lrn_rate, 0.9)
    elif hps.optimizer == 'RMSProp':
      opt = tf.train.RMSPropOptimizer(lrn_rate, decay=RMSPROP_DECAY, momentum=RMSPROP_MOMENTUM, epsilon=RMSPROP_EPSILON)
      
    tower_grads = []
#    debug_ops = []
#    tower_losses = []
    with tf.variable_scope(tf.get_variable_scope()):
      for i in xrange(FLAGS.num_gpus):
        with tf.device('/gpu:%d' % i):
          with tf.name_scope('%s_%d' % (gcnet_model.TOWER_NAME, i)) as scope:
            if i == 0:
              loss, total_variables_to_restore, model_summary = tower_loss(scope, hps, dataset)
            else:
              loss, _, _ = tower_loss(scope, hps, dataset)
#            debug_ops.append(debug_op)
#            tower_losses.append(loss)
            
            # Reuse variables for the next tower.
            tf.get_variable_scope().reuse_variables()
            
            # Retain the summaries from the final tower.
            summaries = tf.get_collection(tf.GraphKeys.SUMMARIES, scope)
            
            # Calculate the gradients for the batch of data on this GC-Net tower.
            grads = opt.compute_gradients(loss)
            
            # Keep track of the gradients across all towers.
            tower_grads.append(grads)
      
    # We must calculate the mean of each gradient. Note that this is the
    # synchronization point across all towers.
    grads = average_gradients(tower_grads)
#    loss = tf.reduce_mean(tf.stack(tower_losses))
    
    # Add a summary to track the learning rate.
#    summaries.append(tf.summary.scalar('learning_rate', lrn_rate))    
    summaries.append(model_summary)
#    summaries.append(tf.summary.scalar('global_step', global_step))  
    
    if FLAGS.debug:
    # Add histograms for gradients.
    # the 'DW' in var.op.name filter only outputs the convolution weights, you can remove this one to monitor all the grads and var
      for grad, var in grads:
        if grad is not None and 'DW' in var.op.name:
          summaries.append(tf.summary.histogram(var.op.name + '/gradients', grad))
        
    # Apply the gradients to adjust the shared variables.
    apply_gradient_op = opt.apply_gradients(grads, global_step=global_step)
    
    if FLAGS.debug:
      # Add histograms for trainable variables.
      for var in tf.trainable_variables():
        if 'DW' in var.name:
          summaries.append(tf.summary.histogram(var.op.name, var))
      
    # Track the moving averages of all trainable variables.
    variable_averages = tf.train.ExponentialMovingAverage(
      gcnet_model.MOVING_AVERAGE_DECAY, global_step)
    variables_averages_op = variable_averages.apply(tf.trainable_variables())
    
    # Group all updates to into a single train op.
    train_op = tf.group(apply_gradient_op, variables_averages_op)
    
    # Create a saver.
    saver = tf.train.Saver(tf.global_variables(), max_to_keep=10, keep_checkpoint_every_n_hours=2.0)
    
    # Build the summary operation from the last tower summaries.
    summary_op = tf.summary.merge(summaries)
    
    # Build an initialization operation to run below.
    init = tf.global_variables_initializer()

    # Start running operations on the Graph. allow_soft_placement must be set to
    # True to build towers on GPU, as some of the ops do not have GPU
    # implementations.
    sess = tf.Session(config=tf.ConfigProto(
      allow_soft_placement=True,
      log_device_placement=FLAGS.log_device_placement))
    
    tf.logging.info("before sess init")
    sess.run(init)

    tf.logging.info("before read ckpt")    
    
    if FLAGS.mode == 'resume':
      assert tf.gfile.Exists(FLAGS.ckpt_path)
      saver.restore(sess, tf.train.latest_checkpoint(FLAGS.ckpt_path))
      tf.logging.info('%s: Resume from %s' %
        (datetime.now(), FLAGS.ckpt_path))
    elif FLAGS.mode == 'retrain':
      assert tf.gfile.Exists(FLAGS.ckpt_path)
      restorer = tf.train.Saver(total_variables_to_restore)
      restorer.restore(sess, tf.train.latest_checkpoint(FLAGS.ckpt_path))
      tf.logging.info('%s: Pre-trained model restored from %s' %
            (datetime.now(), FLAGS.ckpt_path))


    # Start the queue runners.
    tf.train.start_queue_runners(sess=sess)
    
    summary_writer = tf.summary.FileWriter(FLAGS.train_dir, sess.graph)
    
    for step in xrange(FLAGS.max_steps):     

      start_time = time.time()
      if step % 50 == 0:
#        if FLAGS.debug:
#          run_options = tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE)
#          run_metadata = tf.RunMetadata()
#          _, loss_value = sess.run([train_op,  loss],
#                                    options=run_options,
#                                    run_metadata=run_metadata)
#          summary_writer.add_run_metadata(run_metadata, 'step%03d' % step)
#          print('Adding run metadata for', step)
#        else:
        _, loss_value = sess.run([train_op, loss])
        summary_str = sess.run(summary_op)
        summary_writer.add_summary(summary_str, step)

      else:
        _, loss_value = sess.run([train_op, loss])
      duration = time.time() - start_time

      assert not np.isnan(loss_value), 'Model diverged with loss = NaN'

      if step % 20 == 0:
        num_examples_per_step = FLAGS.batch_size * FLAGS.num_gpus
        examples_per_sec = num_examples_per_step / duration
        sec_per_batch = duration / FLAGS.num_gpus

        format_str = ('%s: step %d, loss = %.2f (%.1f examples/sec; %.3f '
                      'sec/batch)')
        tf.logging.info(format_str % (datetime.now(), step, loss_value,
                             examples_per_sec, sec_per_batch))

      # Save the model checkpoint periodically.
      if step % 1000 == 0 or (step + 1) == FLAGS.max_steps:
        checkpoint_path = os.path.join(FLAGS.train_dir, 'model.ckpt')
        saver.save(sess, checkpoint_path, global_step=step)

def main(_):
  if FLAGS.num_gpus == 0:
    raise ValueError('Only support multi gpu.')

#  dataset = SceneFlowData('train')
  dataset = KITTIData('train')
  assert dataset.data_files()

  FLAGS.train_dir = os.path.join(FLAGS.log_root, 'train')
  if tf.gfile.Exists(FLAGS.train_dir):
    tf.gfile.DeleteRecursively(FLAGS.train_dir)
  tf.gfile.MakeDirs(FLAGS.train_dir)

  hps = gcnet_model.HParams(batch_size=BATCH_SIZE,
                             lrn_rate=0.0001,
                             weight_decay_rate=0.0002,
                             relu_leakiness=0.1,
                             optimizer='RMSProp',
                             max_disparity=192) 

  train(hps, dataset)


if __name__ == '__main__':
  tf.logging.set_verbosity(tf.logging.INFO)
  tf.app.run()
