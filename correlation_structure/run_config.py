"""RunConfig class handles the actual workflow logic."""

from correlation_structure.run_data import RunData
from correlation_structure.pair_data import MultiPair
from correlation_structure.plugin_configs import TrainingPluginConfig, ConvergencePluginConfig, ProductionPluginConfig, PluginConfig
from correlation_structure.directory_helper import DirectoryHelper
from copy import deepcopy
import os
import shutil
import logging
import gmx
import json
# import atexit


class RunConfig:
    """Run configuration for single BRER ensemble member."""

    def __init__(self, tpr, ensemble_dir, ensemble_num=1, work_sample=1, pairs_json='pair_data.json'):
        """The run configuration specifies the files and directory structure
        used for the run. It determines whether the run is in the training,
        convergence, or production phase, then performs the run.

        Parameters
        ----------
        tpr : str
            path to tpr. Must be gmx 2017 compatible.
        ensemble_dir : str
            path to top directory which contains the full ensemble.
        ensemble_num : int, optional
            the ensemble member to run, by default 1
        work_sample: int, optional
            the work sample number. Used in convergence and production phases.
        pairs_json : str, optional
            path to file containing *ALL* the pair metadata.
            An example of what such a file should look like is provided in the data directory,
            by default 'pair_data.json'
        """
        self.tpr = tpr
        self.ens_dir = ensemble_dir
        self.work_sample = work_sample

        # a list of identifiers of the residue-residue pairs that will be restrained
        self.__names = []

        # Load the pair data from a json. Use this to set up the run metadata
        self.pairs = MultiPair()
        self.pairs.read_from_json(pairs_json)
        # use the same identifiers for the pairs here as those provided in the pair metadata
        # file this prevents mixing up pair data amongst the different pairs (i.e.,
        # accidentally applying the restraints for pair 1 to pair 2.)
        self.__names = self.pairs.names

        self.run_data = RunData()
        self.run_data.set(ensemble_num=ensemble_num)

        os.makedirs('{}/mem_{}'.format(ensemble_dir, ensemble_num), exist_ok=True)

        self.state_json = '{}/mem_{}/state.json'.format(ensemble_dir, self.run_data.get('ensemble_num'))
        # If we're in the middle of a run, load the BRER checkpoint file and continue from
        # the current state.
        if os.path.exists(self.state_json):
            self.run_data.from_dictionary(json.load(open(self.state_json)))
        # Otherwise, populate the state information using the pre-loaded pair data. Then save
        # the current state.
        else:
            for pd in self.pairs:
                self.run_data.from_pair_data(pd)
            self.run_data.save_config(self.state_json)

        # List of plugins
        self.__plugins = []

        # Logging
        self._logger = logging.getLogger('BRER')
        self._logger.setLevel(logging.DEBUG)
        # create file handler which logs even debug messages
        fh = logging.FileHandler('brer{}.log'.format(ensemble_num))
        fh.setLevel(logging.DEBUG)
        # create console handler with a higher log level
        ch = logging.StreamHandler()
        ch.setLevel(logging.DEBUG)
        # create formatter and add it to the handlers
        formatter = logging.Formatter('%(asctime)s:%(name)s:%(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        ch.setFormatter(formatter)
        # add the handlers to the logger
        self._logger.addHandler(fh)
        self._logger.addHandler(ch)

        self._logger.info("Initialized the run configuration: {}".format(self.run_data.as_dictionary()))
        self._logger.info("Names of restraints: {}".format(self.__names))

        # Need to cleanly handle cancelled jobs: write out a checkpoint of the state if the
        # job is exited.
        # def cleanup():
        #     """"""
        #     self.run_data.save_config(self.state_json)
        #     self._logger.info("BRER received INT signal, stopping and saving data to {}".format(self.state_json))

        # atexit.register(cleanup)

    def build_plugins(self, plugin_config: PluginConfig):
        """Builds the plugin configuration. For each pair-wise restraint,
        populate the plugin with data: both the "general" data and the data
        unique to that restraint.

        Parameters
        ----------
        plugin_config : PluginConfig
            the particular plugin configuration (Training, Convergence, Production) for the run.
        """

        # One plugin per restraint.
        # TODO: what is the expected behavior when a list of plugins exists? Probably wipe them.
        self.__plugins = []
        general_params = self.run_data.general_params
        # For each pair-wise restraint, populate the plugin with data: both the "general" data and
        # the data unique to that restraint.
        for name in self.__names:
            pair_params = self.run_data.pair_params[name]
            new_restraint = deepcopy(plugin_config)
            new_restraint.scan_metadata(general_params)  # load general data into current restraint
            new_restraint.scan_metadata(pair_params)  # load pair-specific data into current restraint
            self.__plugins.append(new_restraint.build_plugin())

    def __change_directory(self):
        # change into the current working directory (ensemble_path/member_path/iteration/phase)
        param_dict = self.run_data.general_params.get_as_dictionary()
        phase = self.run_data.get('phase')

        if phase != 'training':
            param_dict['work_sample'] = self.work_sample

        dir_help = DirectoryHelper(top_dir=self.ens_dir, param_dict=param_dict)
        dir_help.build_working_dir()

        if phase == 'training':
            dir_help.change_dir('phase')
        else:
            dir_help.change_dir('work_sample')

    def __move_cpt(self):
        current_iter = self.run_data.get('iteration')
        ens_num = self.run_data.get('ensemble_num')
        phase = self.run_data.get('phase')
        work_sample = self.work_sample

        if phase == 'training':
            updated_path = '{}/mem_{}/{}/{}/state.cpt'.format(self.ens_dir, ens_num, current_iter, phase)
        else:
            updated_path = '{}/mem_{}/{}/{}/{}/state.cpt'.format(self.ens_dir,
                                                                 ens_num, current_iter, phase, work_sample)
        # If the cpt already exists, don't overwrite it
        if os.path.exists(updated_path):
            self._logger.info("Phase is {} and state.cpt already exists: not moving any files".format(phase))

        else:
            member_dir = '{}/mem_{}'.format(self.ens_dir, ens_num)
            prev_iter = current_iter - 1

            if phase in ['training', 'convergence']:
                if prev_iter > -1:
                    raise ValueError("""Correlation structure calculations do not support multiple iterations yet!
                                     You're trying to run iteration {}""".format(current_iter))
                else:
                    pass  # Do nothing
            else:
                # Get the convergence cpt from current iteration
                gmx_cpt = '{}/{}/convergence/{}/state.cpt'.format(member_dir, current_iter, work_sample)
                shutil.copy(gmx_cpt, '{}/state.cpt'.format(os.getcwd()))

    def __train(self):

        # do re-sampling
        targets = self.pairs.re_sample()
        while self.run_data.history.check_targets(targets):
            targets = self.pairs.re_sample()

        self._logger.info('New targets: {}'.format(targets))

        for name in self.__names:
            self.run_data.set(name=name, target=targets[name])

        # save the new targets to the BRER checkpoint file.
        self.run_data.save_config(fnm=self.state_json)

        # backup existing checkpoint.
        # TODO: Don't backup the cpt, actually use it!!
        cpt = '{}/state.cpt'.format(os.getcwd())
        if os.path.exists(cpt):
            self._logger.warning('There is a checkpoint file in your current working directory, but you are '
                                 'training. The cpt will be backed up and the run will start over with new targets')
            shutil.move(cpt, '{}.bak'.format(cpt))

        # If this is not the first BRER iteration, grab the checkpoint from the production
        # phase of the last round
        self.__move_cpt()

        # Set up a dictionary to go from plugin name -> restraint name
        sites_to_name = {}

        # Build the gmxapi session.
        md = gmx.workflow.from_tpr(self.tpr, append_output=False)
        self.build_plugins(TrainingPluginConfig())
        for plugin in self.__plugins:
            plugin_name = plugin.name
            for name in self.__names:
                run_data_sites = "{}".format(self.run_data.get('sites', name=name))
                if run_data_sites == plugin_name:
                    sites_to_name[plugin_name] = name
            md.add_dependency(plugin)
        context = gmx.context.ParallelArrayContext(md, workdir_list=[os.getcwd()])

        # Run it.
        with context as session:
            session.run()

        # In the future runs (convergence, production) we need the ABSOLUTE VALUE of alpha.
        self._logger.info("=====TRAINING INFO======\n")

        alphas = {}
        for i in range(len(self.__names)):
            current_name = sites_to_name[context.potentials[i].name]
            current_alpha = context.potentials[i].alpha
            current_target = context.potentials[i].target

            alphas[current_name] = current_alpha
            self.run_data.set(name=current_name, alpha=current_alpha)
            self.run_data.set(name=current_name, target=current_target)

            self._logger.info("Plugin {}: alpha = {}, target = {}".format(current_name, current_alpha, current_target))

        self.run_data.history.new_entry(alphas, targets)

    def __converge(self):

        self.__move_cpt()

        md = gmx.workflow.from_tpr(self.tpr, append_output=False)
        self.build_plugins(ConvergencePluginConfig())
        for plugin in self.__plugins:
            md.add_dependency(plugin)
        context = gmx.context.ParallelArrayContext(md, workdir_list=[os.getcwd()])
        with context as session:
            session.run()

        # Get the absolute time (in ps) at which the convergence run finished.
        # This value will be needed if a production run needs to be restarted.
        self.run_data.set(start_time=context.potentials[0].time)

        self._logger.info("=====CONVERGENCE INFO======\n")
        for name in self.__names:
            current_alpha = self.run_data.get('alpha', name=name)
            current_target = self.run_data.get('target', name=name)
            self._logger.info("Plugin {}: alpha = {}, target = {}".format(name, current_alpha, current_target))

    def __production(self):

        # Get the checkpoint file from the convergence phase
        self.__move_cpt()

        # Calculate the time (in ps) at which the BRER iteration should finish.
        # This should be: the end time of the convergence run + the amount of time for
        # production simulation (specified by the user).
        end_time = self.run_data.get('production_time') + self.run_data.get('start_time')

        md = gmx.workflow.from_tpr(self.tpr, end_time=end_time, append_output=False)

        self.build_plugins(ProductionPluginConfig())
        for plugin in self.__plugins:
            md.add_dependency(plugin)
        context = gmx.context.ParallelArrayContext(md, workdir_list=[os.getcwd()])
        with context as session:
            session.run()

        self._logger.info("=====PRODUCTION INFO======\n")
        for name in self.__names:
            current_alpha = self.run_data.get('alpha', name=name)
            current_target = self.run_data.get('target', name=name)
            self._logger.info("Plugin {}: alpha = {}, target = {}".format(name, current_alpha, current_target))

    def run(self, set_next_phase=False):
        """Perform the MD simulations.
        """
        phase = self.run_data.get('phase')

        self.__change_directory()

        if phase == 'training':
            self.__train()
            self.run_data.set(phase='convergence')
        elif phase == 'convergence':
            self.__converge()
            if set_next_phase:
                self.run_data.set(phase='production')
        else:
            self.__production()
            if set_next_phase:
                self.run_data.set(phase='training', start_time=0, iteration=(self.run_data.get('iteration') + 1))

        self.run_data.save_config(self.state_json)
