import os
from pandas import read_csv
import matplotlib.pyplot as plt
from ksrates.utils import init_logging
import logging
import sys
from numpy import arange
import ksrates.fc_configfile as fcConf
import ksrates.fc_check_input as fcCheck
import ksrates.fc_plotting as fcPlot
import ksrates.fc_extract_ks_list as fc_extract_ks_list
import ksrates.fc_lognormal_mixture as fcLMM
from ksrates.fc_plotting import COLOR_ANCHOR_HISTOGRAM
from ksrates.fc_cluster_anchors import subfolder
from ksrates.fc_rrt_correction import _ADJUSTMENT_TABLE

def lognormal_mixture(config_file, expert_config_file, paralog_tsv_file, anchors_ks_tsv_file, correction_table_file):
    # INPUT
    config = fcConf.Configuration(config_file, expert_config_file)
    init_logging(f"Lognormal mixture model on Ks distribution", config.get_logging_level())
    logging.info("Loading parameters and input files")

    paranome_analysis = config.get_paranome()
    colinearity_analysis = config.get_colinearity()
    species = config.get_species()
    latin_names = config.get_latin_names()
    latinSpecies = latin_names[species]
    species_escape_whitespace = latinSpecies.replace(' ', '\ ')
    max_ks_para = config.get_max_ks_para()
    min_ks_anchors = config.get_min_ks_anchors()
    bin_width_para = config.get_bin_width_para()
    bin_list = fcPlot.get_bins(max_ks_para, bin_width_para)
    x_max_lim = config.get_x_max_lim()
    y_lim = config.get_y_lim()  # by default it's "None"
    kde_bandwidth_modifier = config.get_kde_bandwidth_modifier()
    color_list = config.get_color_list()
    plot_correction_arrows = config.plot_correction_arrows()
    # Getting the statistical measure for how to determine the representative value of an ortholog distribution
    peak_stats = config.get_peak_stats() # default is mode (other option, median)
    # Getting the choice on how to deal with the presence of multiple corrections for the same divergent pair
    consensus_peak_for_multiple_outgroups = config.get_consensus_peak_for_multiple_outgroups()
    
    # Parameters used during the mixture modeling
    max_ks_EM = config.get_max_ks_for_mixture_model(max_ks_para) # upper Ks limit considered for the mixture model fitting
    max_EM_iterations = config.get_max_EM_iterations() # default 600
    num_EM_initializations = config.get_num_EM_initializations() # how many time k-means is performed. Default 10.
    max_num_comp = config.get_max_mixture_model_components()

    logging.info(f" - maximum EM iterations: {max_EM_iterations}")
    logging.info(f" - number of EM initializations: {num_EM_initializations}")
    logging.info(f" - maximum number of components: {max_num_comp}")
    if max_ks_EM != max_ks_para:
        logging.info(f" - Ks range considered for the mixture modeling: up to {max_ks_EM} Ks.")
    logging.info("")

    # Creating folder for secondary output files
    output_dir = os.path.join("rate_adjustment", species, subfolder)
    if not os.path.isdir(output_dir):
        logging.info(f"Creating directory [{output_dir}]")
        logging.info("")
        os.makedirs(output_dir)

    # Get correction results TSV file
    # If correction_table is (still) missing, it will be equal to empty string (""), but the script will not exit
    default_path_correction_table_file = os.path.join("rate_adjustment", f"{species}", f"{_ADJUSTMENT_TABLE.format(species)}")
    correction_table_file = fcCheck.get_argument_path(correction_table_file, default_path_correction_table_file, "Rate-adjustment table file")
    if correction_table_file == "":
        logging.warning("Rate-adjustment data are not available yet, only Ks distribution will be plotted.")
        correction_table = None
        correction_table_available = False
    else:
        with open(correction_table_file, "r") as f:
            correction_table = read_csv(f, sep="\t")
            correction_table_available = True

    # Get paralog and anchors TSV files
    # If a Ks file is not required, it will be equal to "None";
    # If the required input Ks file (paranome or anchor pairs or both) is missing,
    # its path will be qual to an empty string ("") and the script will exit
    if paranome_analysis:
        default_path_paralog_tsv_file = os.path.join("paralog_distributions", f"wgd_{species}", f"{species}.ks.tsv")
        paralog_tsv_file = fcCheck.get_argument_path(paralog_tsv_file, default_path_paralog_tsv_file, "Paralog Ks TSV file")
        if paralog_tsv_file == "":
            logging.error(f"Paralog Ks TSV file not found at default position [{default_path_paralog_tsv_file}].")
    if colinearity_analysis:
        default_path_anchors_tsv_file = os.path.join("paralog_distributions", f"wgd_{species}", f"{species}.ks_anchors.tsv")
        anchors_ks_tsv_file = fcCheck.get_argument_path(anchors_ks_tsv_file, default_path_anchors_tsv_file, "Anchor pair Ks TSV file")
        if anchors_ks_tsv_file == "":
            logging.error(f"Anchor pair Ks TSV file not found at default position [{default_path_anchors_tsv_file}].")
    if paralog_tsv_file == "" or anchors_ks_tsv_file == "":
        logging.error("Exiting")
        sys.exit(1)

    fig_para, axis_para = fcPlot.generate_mixed_plot_figure(latin_names.get(species), x_max_lim, y_lim, "corrected",
                    correction_table_available, plot_correction_arrows, paranome_data=True, colinearity_data=False)
    fig_colin, axis_colin = fcPlot.generate_mixed_plot_figure(latin_names.get(species), x_max_lim, y_lim, "corrected",
                    correction_table_available, plot_correction_arrows, paranome_data=False, colinearity_data=True)

    parameter_table = []

    if paranome_analysis:
        with open (os.path.join("rate_adjustment", f"{species}", subfolder, f"lmm_{species}_parameters_paranome.txt"), "w+") as outfile:
            logging.info("Performing lognormal mixture model on whole-paranome Ks distribution")
            paranome_list, paranome_weights = fc_extract_ks_list.ks_list_from_tsv(paralog_tsv_file, max_ks_para, "paralogs")
            hist_paranome = fcPlot.plot_histogram("Whole-paranome", axis_para, paranome_list, bin_list, 
                                        bin_width_para, max_ks_para, kde_bandwidth_modifier, paranome_weights, plot_kde=False)
            # Setting the plot height based on tallest histogram bin
            if y_lim is None:
                fcPlot.set_mixed_plot_height(axis_para, y_lim, hist_paranome)

            best_model_paranome = fcLMM.lmm(
                    fig_para, x_max_lim, "paralogs", paralog_tsv_file, species, axis_para, (0, max_ks_EM), min_ks_anchors,
                    (1, max_num_comp), arange(-10, max_ks_EM + bin_width_para, bin_width_para), bin_width_para, max_EM_iterations, num_EM_initializations,
                    output_dir, outfile, parameter_table, "paranome", peak_stats, correction_table_available, plot_correction_arrows)
        
            # Generating tabular text file with all model parameters 
            fcLMM.make_parameter_table_file(parameter_table, species, "paranome")
        
    if paranome_analysis and colinearity_analysis:
        logging.info("")
        parameter_table = []

    if colinearity_analysis:
        with open (os.path.join("rate_adjustment", f"{species}", subfolder, f"lmm_{species}_parameters_anchors.txt"), "w+") as outfile:
            logging.info("Performing lognormal mixture model on anchor pair Ks distribution")

            anchors_list, anchors_weights = fc_extract_ks_list.ks_list_from_tsv(anchors_ks_tsv_file, max_ks_para, "anchor pairs")
            
            # Remove anchor Ks values that are smaller than min_ks_anchors
            anchors_list_filtered = [val for val in anchors_list if val >= min_ks_anchors]
            anchors_weights_filtered = [w for val, w in zip(anchors_list, anchors_weights) if val >= min_ks_anchors]

            if len(anchors_list) == 0:
                logging.warning(f"No anchor pairs found! Maybe check your (gene) IDs between "
                                f"the [*species*.ks_anchors.tsv] file and the [*species*.ks.tsv] files.")
            hist_anchors = fcPlot.plot_histogram("Anchor pairs", axis_colin, anchors_list_filtered, bin_list, bin_width_para,
                                        max_ks_para, kde_bandwidth_modifier, anchors_weights_filtered, color=COLOR_ANCHOR_HISTOGRAM, plot_kde=False)
            # Setting the plot height based on tallest histogram bin
            if y_lim is None:
                fcPlot.set_mixed_plot_height(axis_colin, y_lim, hist_anchors)

            best_model_anchors = fcLMM.lmm(
                    fig_colin, x_max_lim, "anchor pairs", anchors_ks_tsv_file, species, axis_colin, (0, max_ks_EM), min_ks_anchors,
                    (1, max_num_comp), arange(-10, max_ks_EM + bin_width_para, bin_width_para), bin_width_para, max_EM_iterations, num_EM_initializations,
                    output_dir, outfile, parameter_table, "anchors", peak_stats, correction_table_available, plot_correction_arrows)

            # Generating tabular text file with all model parameters 
            fcLMM.make_parameter_table_file(parameter_table, species, "anchors")

    for axis in [axis_para, axis_colin]:
        # PLOTTING THE ORTHOLOG DIVERGENCE LINES
        if correction_table_available:
            dummy_fig, dummy_axis = plt.subplots()
            fcPlot.plot_divergences(correction_table, peak_stats, consensus_peak_for_multiple_outgroups, dummy_axis, axis, color_list, plot_correction_arrows)

    logging.info("")

    if paranome_analysis:
        fcLMM.save_lmm(fig_para, axis_para, species, best_model_paranome, "paranome", correction_table_available)
        logging.info(f"Saved PDF figure of lognormal mixture model [mixed_{species}_lmm_paranome.pdf]")
    if colinearity_analysis:
        fcLMM.save_lmm(fig_colin, axis_colin, species, best_model_anchors, "anchors", correction_table_available)
        logging.info(f"Saved PDF figure of lognormal mixture model [mixed_{species}_lmm_anchors.pdf]")

    logging.info("")
    logging.info("All done")