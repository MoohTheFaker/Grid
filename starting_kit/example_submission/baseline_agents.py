import pypownet.agent
import pypownet.environment
import numpy as np
import os

class ActIOnManager(object):
    def __init__(self, destination_path='saved_actions.csv', delete=True):
        self.actions = []
        self.destination_path = destination_path
        print('Storing actions at', destination_path)

        # Delete last path with same name by default!!!
        if delete and os.path.exists(destination_path):
            os.remove(destination_path)

    def dump(self, action):
        with open(self.destination_path, 'a') as f:
            f.write(','.join([str(int(switch)) for switch in action.as_array()]) + '\n')

    @staticmethod
    def load(filepath):
        with open(filepath, 'r') as f:
            lines = f.read().splitlines()
        actions = [[int(l) for l in line.split(',')] for line in lines]
        assert 0 in np.unique(actions) and 1 in np.unique(actions) and len(np.unique(actions)) == 2
        return actions

class GreedySearch(pypownet.agent.Agent):
    """ This agent is a tree-search model of depth 1, that is constrained to modifiying at most 1 substation
    configuration or at most 1 line status. This controler used the simulate method of the environment, by testing
    every 1-line status switch action, every new configuration for substations with at least 4 elements, as well as
    the do-nothing action. Then, it will seek for the best reward and return the associated action, expecting
    the maximum reward for the action pool it can reach.
    Note that the simulate method is only an approximation of the step method of the environment, and in three ways:
    * simulate uses the DC mode, while step is in AC
    * simulate uses only the predictions given to the player to simulate the next timestep injections
    * simulate can not compute the hazards that are supposed to come at the next timestep
    """

    def __init__(self, environment):
        super().__init__(environment)
        self.verbose = True

        self.ioman = ActIOnManager(destination_path='saved_actions.csv')

    def act(self, observation):
        import itertools

        # Sanity check: an observation is a structured object defined in the environment file.
        assert isinstance(observation, pypownet.environment.Observation)
        action_space = self.environment.action_space

        number_lines = action_space.lines_status_subaction_length
        # Will store reward, actions, and action name, then eventually pick the maximum reward and retrieve the
        # associated values
        rewards, actions, names = [], [], []

        # Test doing nothing
        if self.verbose:
            print(' Simulation with no action', end='')
        action = action_space.get_do_nothing_action()
        reward_aslist = self.environment.simulate(action, do_sum=False)
        reward = sum(reward_aslist)
        if self.verbose:
            print('; reward: [', ', '.join(['%.2f' % c for c in reward_aslist]), '] =', reward)
        rewards.append(reward)
        actions.append(action)
        names.append('no action')

        # Test every line opening
        for l in range(number_lines):
            if self.verbose:
                print(' Simulation with switching status of line %d' % l, end='')
            action = action_space.get_do_nothing_action()
            action_space.set_lines_status_switch_from_id(action=action, line_id=l, new_switch_value=1)
            reward_aslist = self.environment.simulate(action, do_sum=False)
            reward = sum(reward_aslist)
            if self.verbose:
                print('; reward: [', ', '.join(['%.2f' % c for c in reward_aslist]), '] =', reward)
            rewards.append(reward)
            actions.append(action)
            names.append('switching status of line %d' % l)

        # For every substation with at least 4 elements, try every possible configuration for the switches
        for substation_id in action_space.substations_ids:
            substation_n_elements = action_space.get_number_elements_of_substation(substation_id)
            if 6 > substation_n_elements > 3:
                # Look through all configurations of n_elements binary vector with first value fixed to 0
                for configuration in list(itertools.product([0, 1], repeat=substation_n_elements - 1)):
                    new_configuration = [0] + list(configuration)
                    if self.verbose:
                        print(' Simulation with change in topo of sub. %d with switches %s' % (
                            substation_id, repr(new_configuration)), end='')
                    # Construct action
                    action = action_space.get_do_nothing_action()
                    action_space.set_switches_configuration_of_substation(action=action,
                                                                          substation_id=substation_id,
                                                                          new_configuration=new_configuration)
                    reward_aslist = self.environment.simulate(action, do_sum=False)
                    reward = sum(reward_aslist)
                    if self.verbose:
                        print('; reward: [', ', '.join(['%.2f' % c for c in reward_aslist]), '] =', reward)
                    rewards.append(reward)
                    actions.append(action)
                    names.append('change in topo of sub. %d with switches %s' % (substation_id,
                                                                                 repr(new_configuration)))

        # Take the best reward, and retrieve the corresponding action
        best_reward = max(rewards)
        best_index = rewards.index(best_reward)
        best_action = actions[best_index]
        best_action_name = names[best_index]

        # Dump best action into stored actions file
        self.ioman.dump(best_action)

        if self.verbose:
            print('Action chosen: ', best_action_name, '; expected reward %.4f' % best_reward)

        return best_action

    
class TreeSearchLineServiceStatus(pypownet.agent.Agent):
    """ Exhaustive tree search of depth 1 limited to no action + 1 line switch activation
    """

    def __init__(self, environment):
        super().__init__(environment)
        self.verbose = True

        self.ioman = ActIOnManager(destination_path='saved_actions_TreeSearchLineServiceStatus.csv')

    def act(self, observation):
        # Sanity check: an observation is a structured object defined in the environment file.
        assert isinstance(observation, pypownet.environment.Observation)
        action_space = self.environment.action_space

        number_of_lines = self.environment.action_space.lines_status_subaction_length
        # Simulate the line status switch of every line, independently, and save rewards for each simulation (also store
        # the actions for best-picking strat)
        simulated_rewards = []
        simulated_actions = []
        for l in range(number_of_lines):
            if self.verbose:
                print('    Simulating switch activation line %d' % l, end='')
            # Construct the action where only line status of line l is switched
            action = action_space.get_do_nothing_action()
            action_space.set_lines_status_switch_from_id(action=action, line_id=l, new_switch_value=1)
            simulated_reward = self.environment.simulate(action=action)

            # Store ROI values
            simulated_rewards.append(simulated_reward)
            simulated_actions.append(action)
            if self.verbose:
                print('; expected reward %.5f' % simulated_reward)

        # Also simulate the do nothing action
        if self.verbose:
            print('    Simulating switch activation line %d' % l, end='')
        donothing_action = self.environment.action_space.get_do_nothing_action()
        donothing_simulated_reward = self.environment.simulate(action=donothing_action)
        simulated_rewards.append(donothing_simulated_reward)
        simulated_actions.append(donothing_action)

        # Seek for the action that maximizes the reward
        best_simulated_reward = np.max(simulated_rewards)
        best_action = simulated_actions[simulated_rewards.index(best_simulated_reward)]

        # Dump best action into stored actions file
        self.ioman.dump(best_action)

        if self.verbose:
            print('  Best simulated action: disconnect line %d; expected reward: %.5f' % (
                simulated_rewards.index(best_simulated_reward), best_simulated_reward))

        return best_action

    

class DoNothingAgent(pypownet.agent.Agent):
    def __init__(self, environment):
        super().__init__(environment)

    def act(self, observation):
        """ Produces an action given an observation of the environment. Takes as argument an observation of the current
        power grid, and returns the chosen action."""
        # Sanity check: an observation is a structured object defined in the environment file.
        assert isinstance(observation, pypownet.environment.Observation)

        action_space = self.environment.action_space

        # Implement your policy here
        # Example of the do-nothing policy that produces no action (i.e. an action that does nothing) each time
        do_nothing_action = action_space.get_do_nothing_action()

        # Sanity check: verify the good overall structure of the returned action; raises exceptions if not valid
        assert action_space.verify_action_shape(do_nothing_action)
        return do_nothing_action

class RandomLineSwitch(pypownet.agent.Agent):
    """
    An example of a baseline controler that randomly switches the status of one random power line per timestep (if the
    random line is previously online, switch it off, otherwise switch it on).
    """

    def __init__(self, environment):
        super().__init__(environment)
        self.verbose = True

    def act(self, observation):
        # Sanity check: an observation is a structured object defined in the environment file.
        assert isinstance(observation, pypownet.environment.Observation)
        action_space = self.environment.action_space

        # Create template of action with no switch activated (do-nothing action)
        action = action_space.get_do_nothing_action()

        # Randomly switch one line
        l = np.random.randint(action_space.lines_status_subaction_length)
        action_space.set_lines_status_switch_from_id(action=action,
                                                     line_id=l,
                                                     new_switch_value=1)

        # Test the reward on the environment
        reward_aslist = self.environment.simulate(action, do_sum=False)
        reward = sum(reward_aslist)
        if self.verbose:
            print('reward: [', ', '.join(['%.2f' % c for c in reward_aslist]), '] =', reward)

        action_name = 'switching status of line %d' % l
        if self.verbose:
            print('Action chosen: ', action_name, '; expected reward %.4f' % reward)

        return action

        # No learning (i.e. self.feed_reward does pass)


class RandomNodeSplitting(pypownet.agent.Agent):
    """ Implements a "random node-splitting" agent: at each timestep, this controler will select a random substation
    (id), then select a random switch configuration such that switched elements of the selected substations change the
    node within the substation on which they are directly wired.
    """

    def __init__(self, environment):
        super().__init__(environment)
        self.verbose = True

    def act(self, observation):
        # Sanity check: an observation is a structured object defined in the environment file.
        assert isinstance(observation, pypownet.environment.Observation)
        action_space = self.environment.action_space

        # Create template of action with no switch activated (do-nothing action)
        action = action_space.get_do_nothing_action()

        # Select a random substation ID on which to perform node-splitting
        target_substation_id = np.random.choice(action_space.substations_ids)
        expected_target_configuration_size = action_space.get_number_elements_of_substation(target_substation_id)
        # Choses a new switch configuration (binary array)
        target_configuration = np.random.choice([0, 1], size=(expected_target_configuration_size,))

        action_space.set_switches_configuration_of_substation(action=action,
                                                              substation_id=target_substation_id,
                                                              new_configuration=target_configuration)

        # Test the reward on the environment
        reward_aslist = self.environment.simulate(action, do_sum=False)
        reward = sum(reward_aslist)
        if self.verbose:
            print('reward: [', ', '.join(['%.2f' % c for c in reward_aslist]), '] =', reward)

        action_name = 'change in topo of sub. %d with switches %s' % (target_substation_id,
                                                                                 repr(target_configuration))
        if self.verbose:
            print('Action chosen: ', action_name, '; expected reward %.4f' % reward)


        # Ensure changes have been done on action
        current_configuration, _ = action_space.get_switches_configuration_of_substation(action, target_substation_id)
        assert np.all(current_configuration == target_configuration)

        return action