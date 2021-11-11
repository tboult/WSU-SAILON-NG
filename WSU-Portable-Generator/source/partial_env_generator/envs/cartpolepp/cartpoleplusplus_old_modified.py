"""
Classic cart-pole system implemented by Rich Sutton et al.
Copied from http://incompleteideas.net/book/code/pole.c
"""
import math
import gym
from gym import spaces
from gym.utils import seeding
import os.path
import numpy as np
import pybullet as p2
from pybullet_utils import bullet_client as bc

import sys
import os
import time


class CartPoleBulletEnv(gym.Env):
    metadata = {'render.modes': ['human', 'rgb_array'], 'video.frames_per_second': 50}

    def __init__(self, use_img=False, renders=False, discrete_actions=True):
        # start the bullet physics server
        self._renders = renders
        self._discrete_actions = discrete_actions
        self._render_height = 480
        self._render_width = 640
        self._physics_client_id = -1
        self.theta_threshold_radians = 12 * 2 * math.pi / 360
        self.x_threshold = 0.4  # 2.4
        self.use_img = use_img
        high = np.array([self.x_threshold * 2, np.finfo(np.float32).max,
                         self.theta_threshold_radians * 2, np.finfo(np.float32).max])

        # Environmental params
        self.force_mag = 10
        self.timeStep = 1.0 / 50.0
        self.angle_limit = 10
        self.actions = ['left', 'right', 'forward', 'backward', 'nothing']

        # Internal params
        self.path = "env_generator/envs/cartpolepp/"
        self.tick_limit = 200
        self.tick = 0
        self.time = None

        # Object definitions
        self.nb_blocks = None
        self.cartpole = -10
        self.ground = None
        self.blocks = list()
        self.walls = None
        self.state = None

        if self._discrete_actions:
            self.action_space = spaces.Discrete(5)
        else:
            action_dim = 1
            action_high = np.array([self.force_mag] * action_dim)
            self.action_space = spaces.Box(-action_high, action_high)

        self.observation_space = spaces.Box(-high, high, dtype=np.float32)

        corners = [[-5, -5, 0],
                   [5, -5, 0],
                   [5, 5, 0],
                   [-5, 5, 0],
                   [-5, -5, 10],
                   [5, -5, 10],
                   [5, 5, 10],
                   [-5, 5, 10]]

        self.get_origin(corners)

        self.seed()
        self.viewer = None
        self._configure()

        return None

    def _configure(self, display=None):
        self.display = display

    def seed(self, seed=None):
        self.np_random, seed = seeding.np_random(seed)
        return [seed]

    def step(self, action):
        p = self._p

        # Convert from string to int
        if action == 'nothing':
            action = 0
        elif action == 'left':
            action = 1
        elif action == 'right':
            action = 2
        elif action == 'forward':
            action = 3
        elif action == 'backward':
            action = 4

        # Handle math first then direction
        cart_deg_angle = self.quaternion_to_euler(*p.getLinkState(self.cartpole, 0)[1])[2]
        cart_angle = (cart_deg_angle) * np.pi / 180

        # Adjust forces so it always apply in reference to world frame
        fx = self.force_mag * np.cos(cart_angle)
        fy = self.force_mag * np.sin(cart_angle) * -1
        # based on action decide the x and y forces
        if action == 0:
            pass
        elif action == 1:
            fx = fx
            #TB.. why no setting of fy.. its leavig as he above?

        elif action == 2:
            fx = -fx
            fy = - fy
        elif action == 3:
            tmp = fx
            fx = -fy
            fy = tmp
        elif action == 4:
            tmp = fx
            fx = fy
            fy = -tmp
        else:
            raise Exception("unknown discrete action [%s]" % action)


        # Apply correccted forces
        p.applyExternalForce(self.cartpole, 0, (fx, fy, 0.0), (0, 0, 0), p.LINK_FRAME)

        # Apply anti-gravity to blocks
        for i in self.blocks:
            p.applyExternalForce(i, -1, (0, 0, 9.8), (0, 0, 0), p.LINK_FRAME)

        p.stepSimulation()

        done = self.is_done()
        reward = self.get_reward()

        self.tick = self.tick + 1

        return self.get_state(), reward, done, {}

    # Check if is done
    def is_done(self):
        # Check tick limit condition
        if self.tick >= self.tick_limit:
            return True

        # Check pole angle condition
        p = self._p
        pos, vel, jRF, aJMT = p.getJointStateMultiDof(self.cartpole, 1)
        pos = self.quaternion_to_euler(*pos)
        x_angle = abs(pos[0])
        y_angle = abs(pos[1])

        if x_angle < self.angle_limit and y_angle < self.angle_limit:
            return False
        else:
            return True

        return None

    def get_reward(self):
        return self.tick / self.tick_limit

    def get_time(self):
        return self.time + self.tick * self.timeStep

    def get_actions(self):
        return self.actions

    def reset(self, feature_vector=None):
        # self.close()
        # Set time paremeter for sensor value
        self.time = time.time()

        # Create client if it doesnt exist
        if self._physics_client_id < 0:
            self.generate_world()

        self.tick = 0
        self.reset_world(feature_vector)

        # Run for one step to get everything going
#        self.step(0)

        return self.get_state(initial=True)

    # Used to generate the initial world state
    def generate_world(self):
        # Create bullet physics client
        if self._renders:
            self._p = bc.BulletClient(connection_mode=p2.GUI)
        else:
            self._p = bc.BulletClient(connection_mode=p2.DIRECT)
            sys.stdout.write("\033[F")
            sys.stdout.write("\033[K") # Clear to the end of line

        # Client id link, for closing or checking if running
        self._physics_client_id = self._p._client

        # Load world simulation
        p = self._p
        p.resetSimulation()
        p.setGravity(0, 0, -9.8)
        p.setTimeStep(self.timeStep)
        p.setRealTimeSimulation(0)

        # Load world objects
        self.cartpole = p.loadURDF(os.path.join(self.path, 'models', 'ground_cart.urdf'))
        self.walls = p.loadURDF(os.path.join(self.path, 'models', 'walls.urdf'))

        # Set walls to be bouncy
        for joint_nb in range(-1, 6):
            p.changeDynamics(self.walls, joint_nb, restitution=1.0, lateralFriction=0.0,
                             rollingFriction=0.0, spinningFriction=0.0)

        return None

    def reset_world(self, feature_vector=None):
        # Reset world (assume is created)
        p = self._p

        # Delete cartpole
        if self.cartpole == -10:
            self.cartpole = p.loadURDF(os.path.join(self.path, 'models', 'ground_cart.urdf'))
        else:
            p.removeBody(self.cartpole)
            self.cartpole = p.loadURDF(os.path.join(self.path, 'models', 'ground_cart.urdf'))

        # This big line sets the spehrical joint on the pole to loose

        p.setJointMotorControlMultiDof(self.cartpole, 1, p.POSITION_CONTROL, targetPosition=[0, 0, 0, 1],
                                       targetVelocity=[0, 0, 0], positionGain=0, velocityGain=0.1,
                                       force=[0, 0, 0])

        if(feature_vector is None):
            # Reset cart (technicaly ground object)
            cart_pos = list(self.np_random.uniform(low=-3, high=3, size=(2,))) + [0]
            cart_vel = list(self.np_random.uniform(low=-1, high=1, size=(2,))) + [0]
        else:
            cart_pos = [feature_vector["cart"]["x_position"],
                        feature_vector["cart"]["y_position"],
                        feature_vector["cart"]["z_position"]
            ]
            cart_vel = [feature_vector["cart"]["x_velocity"],
                        feature_vector["cart"]["y_velocity"],
                        feature_vector["cart"]["z_velocity"]
            ]



        p.resetBasePositionAndOrientation(self.cartpole, [0,0,0], [0, 0, 0, 1])
        p.resetJointStateMultiDof(self.cartpole, 0, targetValue=cart_pos, targetVelocity=cart_vel)



        # Reset pole
        if(feature_vector is None):
            randstate = list(self.np_random.uniform(low=-0.01, high=0.01, size=(6,)))
            #from scipy.spatial.transform import Rotation as R
            #pole_pos = R.random().as_quat();  #TB fix so it is a proper quaterion.
            pole_pos = list(randstate[0:3] + [1])
            # zero so it doesnt spin like a top :)
            pole_vel = list(randstate[3:5]) + [0]
        else:
            # Reset pole
            pole_pos = [feature_vector["pole"]["x_quaternion"],
                        feature_vector["pole"]["y_quaternion"],
                        feature_vector["pole"]["z_quaternion"],
                        feature_vector["pole"]["w_quaternion"]]
            pole_vel = [feature_vector["pole"]["x_velocity"],
                        feature_vector["pole"]["y_velocity"],
                        0]

        p.resetJointStateMultiDof(self.cartpole, 1, targetValue=pole_pos, targetVelocity=pole_vel)


        # Delete old blocks
        for i in self.blocks:
            p.removeBody(i)


        # Load blocks in
        if(feature_vector is None):
            self.nb_blocks = np.random.randint(4) + 1
        else:
            self.nb_blocks = len(feature_vector['blocks']) +1

        self.blocks = [None] * self.nb_blocks
        for i in range(self.nb_blocks):
            self.blocks[i] = p.loadURDF(os.path.join(self.path, 'models', 'block.urdf'))

        # Set blocks to be bouncy
        for i in self.blocks:
            p.changeDynamics(i, -1, restitution=1.0, lateralFriction=0.0,
                             rollingFriction=0.0, spinningFriction=0.0)

        # Set block posistions
        min_dist = 1
        cart_pos, _ = p.getBasePositionAndOrientation(self.cartpole)
        cart_pos = np.asarray(cart_pos)
        if(feature_vector is None):
            for i in self.blocks:
                pos = self.np_random.uniform(low=-4.0, high=4.0, size=(3,))
                pos[2] = pos[2] + 5.0
                while np.linalg.norm(cart_pos[0:2] - pos[0:2]) < min_dist:
                    pos = self.np_random.uniform(low=-4.0, high=4.0, size=(3,))
                    # Z is not centered at 0.0
                    pos[2] = pos[2] + 5.0
                p.resetBasePositionAndOrientation(i, pos, [0, 0, 1, 0])
                vel = self.np_random.uniform(low=6.0, high=10.0, size=(3,))
                for ind, val in enumerate(vel):
                    if np.random.rand() < 0.5:
                        vel[ind] = val * -1
                p.resetBaseVelocity(i, vel, [0, 0, 0])
        else: # copy blocks from feature vector
            for block in feature_vector["blocks"]:
                pos = [block["x_position"],
                       block["y_position"],
                       block["z_position"]]
                vel = [block["x_velocity"],
                       block["y_velocity"],
                       block["z_velocity"]]


                #p.resetBasePositionAndOrientation(block, pos, [0, 0, 1, 0])
                #p.resetBaseVelocity(i, vel, [0, 0, 0])
        return None


    def savebul(self,filename):
        p = self._p
        p.saveBullet(filename)

    def restorebul(self,filename):
        p = self._p
        # this failes with no error about number of bodies not matchine.. since it was its own save/resore I presume its just broen.
        p.loadBullet(bulletFileName="/net/home/store/home/tboult/WORK/cartpole_3d/env.bullet")


    def state_diff(self,astate):
        mystate = self.get_state();
        diff = dict()
        diffc= { key : round(mystate['cart'][key] - astate['cart'][key],6) for key in astate['cart'] if key in mystate['cart'] }
        diffp = { key : round(mystate['pole'][key] - astate['pole'][key],6) for key in astate['pole'] if key in mystate['pole'] }
        carray = ([(val) for (key,val) in diffc.items()])
        parray = ([(val) for (key,val) in diffp.items()])
        return carray,parray

    # Unified function for getting state information
    def get_state(self, initial=False):
        p = self._p
        world_state = dict()
        round_amount = 16    #round to double precision

        # Get cart info ============================================
        state = dict()

        # Handle pos, ori
        base_pose, _ = p.getBasePositionAndOrientation(self.cartpole)
        pos, vel, jRF, aJMT = p.getJointStateMultiDof(self.cartpole, 0)
        #print(pos)
        #print(base_pose)

        state['x_position'] = round(pos[0] + base_pose[0], round_amount)
        state['y_position'] = round(pos[1] + base_pose[1], round_amount)
        state['z_position'] = round(0.1 + base_pose[2], round_amount)

        # Handle velocity
        state['x_velocity'] = round(vel[0], round_amount)
        state['y_velocity'] = round(vel[1], round_amount)
        state['z_velocity'] = round(0.0, round_amount)

        world_state['cart'] = state

        # Get pole info =============================================
        state = dict()
        use_euler = False

        # Position and orientation, the other two not used
        pos, vel, jRF, aJMT = p.getJointStateMultiDof(self.cartpole, 1)

        # Position
        if use_euler:
            # Convert quats to eulers
            eulers = self.quaternion_to_euler(*pos)
            state['x_position'] = round(eulers[0], round_amount)
            state['y_position'] = round(eulers[1], round_amount)
            state['z_position'] = round(eulers[2], round_amount)
        else:
            state['x_quaternion'] = round(pos[0], round_amount)
            state['y_quaternion'] = round(pos[1], round_amount)
            state['z_quaternion'] = round(pos[2], round_amount)
            state['w_quaternion'] = round(pos[3], round_amount)

        # Velocity
        state['x_velocity'] = round(vel[0], round_amount)
        state['y_velocity'] = round(vel[1], round_amount)
        state['z_velocity'] = round(vel[2], round_amount)

        world_state['pole'] = state

        # get block info ====================================
        block_state = list()
        for ind, val in enumerate(self.blocks):
            state = dict()
            state['id'] = val

            pos, _ = p.getBasePositionAndOrientation(val)
            state['x_position'] = round(pos[0], round_amount)
            state['y_position'] = round(pos[1], round_amount)
            state['z_position'] = round(pos[2], round_amount)

            vel, _ = p.getBaseVelocity(val)
            state['x_velocity'] = round(vel[0], round_amount)
            state['y_velocity'] = round(vel[1], round_amount)
            state['z_velocity'] = round(vel[2], round_amount)

            block_state.append(state)

        world_state['blocks'] = block_state

        # Get wall info ======================================
        # Hardcoded cause I don't know how to get the info :(
        if initial:
            state = list()
            state.append([-5, -5, 0])
            state.append([5, -5, 0])
            state.append([5, 5, 0])
            state.append([-5, 5, 0])

            state.append([-5, -5, 10])
            state.append([5, -5, 10])
            state.append([5, 5, 10])
            state.append([-5, 5, 10])

            world_state['walls'] = state

        return world_state

    def get_image(self):
        if self.use_img:
            return self.render()
        else:
            return None

    def render(self, mode='human', close=False, dist='close'):
        if mode == "human":
            self._renders = True

        if dist == 'far':
            base_pos = [4.45, 4.45, 9.8]
            cam_dist = 0.1
            cam_pitch = -45.0
            cam_yaw = 45.0 + 90
            cam_roll = 0.0
            fov = 100

        elif dist == 'close':
            base_pos = [4.45, 4.45, 2.0]
            cam_dist = 0.1
            cam_pitch = -15.0
            cam_yaw = 45.0 + 90
            cam_roll = 0.0
            fov = 60

        elif dist == 'follow':
            base_pose, _ = self._p.getBasePositionAndOrientation(self.cartpole)
            pos, vel, jRF, aJMT = self._p.getJointStateMultiDof(self.cartpole, 0)

            x = pos[0] + base_pose[0]
            y = pos[1] + base_pose[1]

            base_pos = [x, y, 2.0]
            cam_dist = 0.1
            cam_pitch = -15.0
            cam_yaw = 45.0 + 90
            cam_roll = 0.0
            fov = 60

        if self._physics_client_id >= 0:
            view_matrix = self._p.computeViewMatrixFromYawPitchRoll(
                cameraTargetPosition=base_pos,
                distance=cam_dist,
                yaw=cam_yaw,
                pitch=cam_pitch,
                roll=cam_roll,
                upAxisIndex=2)
            proj_matrix = self._p.computeProjectionMatrixFOV(fov=fov,
                                                             aspect=float(self._render_width) /
                                                                    self._render_height,
                                                             nearVal=0.1,
                                                             farVal=100.0)
            (_, _, px, _, _) = self._p.getCameraImage(
                width=self._render_width,
                height=self._render_height,
                renderer=self._p.ER_BULLET_HARDWARE_OPENGL,
                viewMatrix=view_matrix,
                projectionMatrix=proj_matrix)
        else:
            px = np.array([[[255, 255, 255, 255]] * self._render_width] * self._render_height, dtype=np.uint8)
        rgb_array = np.array(px, dtype=np.uint8)
        rgb_array = np.reshape(np.array(px), (self._render_height, self._render_width, -1))
        rgb_array = rgb_array[:, :, :3]
        return rgb_array

    def configure(self, args):
        pass

    def eulerToQuaternion(self, yaw, pitch, roll):
        qx = np.sin(yaw / 2) * np.sin(pitch / 2) * np.cos(roll / 2) + np.cos(yaw / 2) * np.cos(pitch / 2) * np.sin(
            roll / 2)
        qy = np.sin(yaw / 2) * np.cos(pitch / 2) * np.cos(roll / 2) + np.cos(yaw / 2) * np.sin(pitch / 2) * np.sin(
            roll / 2)
        qz = np.cos(yaw / 2) * np.sin(pitch / 2) * np.cos(roll / 2) - np.sin(yaw / 2) * np.cos(pitch / 2) * np.sin(
            roll / 2)
        qw = np.cos(yaw / 2) * np.cos(pitch / 2) * np.cos(roll / 2) - np.sin(yaw / 2) * np.sin(pitch / 2) * np.sin(
            roll / 2)

        return (qx, qy, qz, qw)

    def quaternion_to_euler(self, x, y, z, w):
        ysqr = y * y

        t0 = +2.0 * (w * x + y * z)
        t1 = +1.0 - 2.0 * (x * x + ysqr)
        X = np.degrees(np.arctan2(t0, t1))

        t2 = +2.0 * (w * y - z * x)
        t2 = np.where(t2 > +1.0, +1.0, t2)
        # t2 = +1.0 if t2 > +1.0 else t2

        t2 = np.where(t2 < -1.0, -1.0, t2)
        # t2 = -1.0 if t2 < -1.0 else t2
        Y = np.degrees(np.arcsin(t2))

        t3 = +2.0 * (w * z + x * y)
        t4 = +1.0 - 2.0 * (ysqr + z * z)
        Z = np.degrees(np.arctan2(t3, t4))

        return (X, Y, Z)

    def close(self):
        if self._physics_client_id >= 0:
            self._p.disconnect()
        self._physics_client_id = -1

    def get_best_action(self, feature_vector):
        '''
            This function computes the best action to take for two step lookahead
             and returns it as a string
            :return: string action
            '''
        # Create dict of scores
        # Key is first action, scores are rated by second action in order
        # left, right, up, down, nothing
        best_action = {"left": [None for i in range(5)],
                       "right": [None for i in range(5)],
                       "forward": [None for i in range(5)],
                       "backward": [None for i in range(5)],
                       "nothing": [None for i in range(5)]}

        for action in best_action.keys():
            # left, left
            best_action[action][0] = self.step_env(feature_vector, [action, 'left'])
            best_action[action][1] = self.step_env(feature_vector, [action, 'right'])
            best_action[action][2] = self.step_env(feature_vector, [action, 'forward'])
            best_action[action][3] = self.step_env(feature_vector, [action, 'backward'])
            best_action[action][4] = self.step_env(feature_vector, [action, 'nothing'])

        best_score = best_action['left'][0][0]
        expected_state = best_action['left'][0][1]
        # print("Best score: ", best_score)
        action = 'left'
        # return the best scoring action
        for i in best_action.keys():
            for j in range(len(best_action[i])):
                # print(best_action[i][j])
                if best_action[i][j][0] < best_score:
                    best_score = best_action[i][j][0]
                    action = i
                    expected_state = best_action[i][j][1]

        return action, expected_state

    def step_env(self, feature_vector, steps):
        '''
        Step the environment with the given steps
        :param env:
        :param feature_vector:
        :param steps:
        :return: Score
        '''
        self.reset(feature_vector)
        self.step(steps[0])
        #print(self.get_state()["pole"])
        state = self.get_state()
        self.step(steps[1])
        return [self.get_score(self.get_state()), state]

    def get_score(self, feature_vector):
        '''
        Score the current state of the environment.
        :return: float score
        '''

        cart_x, cart_y, cart_z = feature_vector["cart"]["x_position"], \
                                 feature_vector["cart"]["y_position"], \
                                 feature_vector["cart"]["z_position"]
        # Convert pole quaternions to euler angle
        pole_x, pole_y, pole_z = self.quaternion_to_euler(feature_vector["pole"]["x_quaternion"],
                                                         feature_vector["pole"]["y_quaternion"],
                                                         feature_vector["pole"]["z_quaternion"],
                                                         feature_vector["pole"]["w_quaternion"])
        # The cost can be the angles of x and y, since that is used to determine env done
        # We want to minimize those so the larger they are the higher the cost
        #print("Pole quat vals: ", [pole_x, pole_y, pole_z])
        cornerScores = 0
        # Get distance
        for corner in self.world_edges:
            dist = math.sqrt((cart_x - corner[0]) ** 2
                             + (cart_y - corner[1]) ** 2
                             + (cart_z - corner[2]) ** 2)

            # Scale
            # World origin should be 0, increase from there
            # Factor by 0.01, angle should have the most important weight
            if dist < self.origin_dist:
                # Weight the dist
                cornerScores += dist * 0.01

        blockSum = 0
        # Get distance of the cart to each block
        for block in feature_vector["blocks"]:
            # Get dist
            blockDist = math.sqrt((cart_x - block["x_position"]) ** 2
                                  + (cart_y - block["y_position"]) ** 2
                                  + (cart_z - block["z_position"]) ** 2)
            # Apply linear penalty function
            blockSum -= abs(blockDist * 0.05)

        cost = abs(pole_x) + abs(pole_y)  #+ blockSum + cornerScores

        return cost

    def get_origin(self, corners):
        '''
        Calculate the midpoint of 1st and 3rd corners to set the environment origin
        :param corners: World corners sent on first call to environment
        :return: None
        '''
        self.world_edges = corners[:3]
        self.origin_dist = math.sqrt((corners[0][0] - corners[2][0]) ** 2
                                     + (corners[0][1] - corners[2][1]) ** 2
                                     + (corners[0][2] - corners[2][2]) ** 2)


class CartPoleContinuousBulletEnv(CartPoleBulletEnv):
    metadata = {'render.modes': ['human', 'rgb_array'], 'video.frames_per_second': 50}

    def __init__(self, renders=False):
        # start the bullet physics server
        CartPoleBulletEnv.__init__(self, renders, discrete_actions=False)
