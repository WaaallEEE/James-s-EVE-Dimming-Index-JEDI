# Standard modules
import os
from astropy.time import Time
from scipy.io.idl import readsav
import numpy as np
import pandas as pd
from collections import OrderedDict
import itertools

# Custom modules
from jpm_logger import JpmLogger

# Declare variables (some with defaults) to be accessed by anything that imports this module
eve_data_path = '/Users/jmason86/Dropbox/Research/Data/EVE/eve_lines_2010121-2014146 MEGS-A Mission Bare Bones.sav'
goes_data_path = '/Users/jmason86/Dropbox/Research/Data/GOES/events/GoesEventsC1MinMegsAEra.sav'
output_path = '/Users/jmason86/Dropbox/Research/Postdoc_NASA/Analysis/Coronal Dimming Analysis/JEDI Catalog/'
logger_filename = 'generate_jedi_catalog'  # 'generate_jedi_catalog'

threshold_time_prior_flare_minutes = 480.0
dimming_window_relative_to_flare_minutes_left = -1.0
dimming_window_relative_to_flare_minutes_right = 1440.0
threshold_minimum_dimming_window_minutes = 120.0
nevents = 5052

n_jobs = 1
verbose = True

eve_lines = None
goes_flare_events = None
logger = None
jedi_csv_filename = None
preflare_hdf_filename = None
jedi_row = None


def init():
    """Initialize the jedi catalog: load the data

        Inputs:
            None.

        Optional Inputs:
            None

        Outputs:
            All outputs are globals accessible by doing import jedi_config
            eve_lines [pandas DataFrame]:                     SDO/EVE level 2 lines data. Stores irradiance, time, and wavelength.
            goes_flare_events[pandas DataFrame]:              Flares as observed by GOES/XRS. Store class, start and peak time
            logger [JpmLogger]:                               A configurable log that can optionally also print to console.
            jedi_csv_filename [str]:                          The unique path/filename for the jedi catalog in this run to be stored in on disk.
            preflare_hdf_filename [str]:                      The path/filename of the computed pre-flare irradiances.
            all_minutes_since_last_flare [numpy float array]: The amount of time between each flare.
            preflare_indices [numpy int array]:               The indices where flares are considered time-independent.

        Optional Outputs:
             None

        Example:
            jedi_config.init()
    """
    global eve_lines, goes_flare_events, logger, jedi_csv_filename, preflare_hdf_filename, all_minutes_since_last_flare, preflare_indices

    # Initialize logger
    logger = JpmLogger(filename=logger_filename, path=output_path, console=False)
    logger.info('Logger initialized.')

    # Set up filenames
    jedi_csv_filename = output_path + 'jedi_{0}.csv'.format(Time.now().iso)
    preflare_hdf_filename = os.path.join(output_path, 'preflare_df.hdf5')

    # Load the EVE data
    # TODO: Replace this shortcut method with the method I'm building into sunpy
    logger.info('Loading EVE data.')
    eve_readsav = readsav(eve_data_path)
    irradiance = eve_readsav['irradiance'].byteswap().newbyteorder()  # pandas doesn't like big endian
    irradiance[irradiance == -1] = np.nan
    wavelengths = eve_readsav['wavelength']
    wavelengths_str = []
    [wavelengths_str.append('{0:1.1f}'.format(wavelength)) for wavelength in wavelengths]
    eve_lines = pd.DataFrame(irradiance, columns=wavelengths_str)
    eve_lines.index = pd.to_datetime(eve_readsav.iso.astype(str))
    eve_lines.sort_index(inplace=True)
    eve_lines = eve_lines.drop_duplicates()

    # Get GOES flare events above C1 within date range corresponding to EVE data
    # flares = get_goes_flare_events(eve_lines.index[0], eve_lines.index[-1], verbose=verbose)  # TODO: The method in sunpy needs fixing, issue 2434

    # Load GOES events from IDL saveset instead of directly through sunpy
    logger.info('Loading GOES flare events.')
    goes_flare_events = readsav(goes_data_path)
    goes_flare_events['class'] = goes_flare_events['class'].astype(str)
    goes_flare_events['event_peak_time_human'] = goes_flare_events['event_peak_time_human'].astype(str)
    goes_flare_events['event_start_time_human'] = goes_flare_events['event_start_time_human'].astype(str)
    goes_flare_events['peak_time'] = Time(goes_flare_events['event_peak_time_jd'], format='jd', scale='utc')
    goes_flare_events['start_time'] = Time(goes_flare_events['event_start_time_jd'], format='jd', scale='utc')
    #t = pd.to_datetime(goes_flare_events['event_start_time_jd'], unit='D', origin='julian')  # TODO: Is this the thing that rounds flare time to 00 seconds?

    # Compute the amount of time between all flares [minutes]
    peak_time = goes_flare_events['peak_time']
    all_minutes_since_last_flare = (peak_time[1:] - peak_time[0:-1]).sec / 60.0

    # Figure out which flares are independent, store those indices
    is_flare_independent = all_minutes_since_last_flare > threshold_time_prior_flare_minutes
    preflare_indices = np.where(is_flare_independent)[0] + 1  # Add 1 to map back to event index and not to the differentiated vector


def init_jedi_row():
    """Internal-use function for defining the column headers in the JEDI catalog and starting a fresh csv file on disk

        Inputs:
            None. Draws from the globals set up in init. So you must run the init function before calling this function.

        Optional Inputs:
            None

        Outputs:
            jedi_row [pandas DataFrame]: A ~24k column DataFrame with only a single row populated with np.nan's.

        Optional Outputs:
             None

        Example:
            jedi_row = init_jedi_row()
    """
    global jedi_row

    jedi_row = pd.DataFrame(
        OrderedDict((
            ('Event #', pd.Series(np.arange(nevents))),
            ('GOES Flare Start Time', ''),
            ('GOES Flare Peak Time', ''),
            ('GOES Flare Class', ''),
            ('Pre-Flare Start Time', ''),
            ('Pre-Flare End Time', ''),
            ('Flare Interrupt', np.nan)
        ))
    )

    # Define the combination of columns of the JEDI catalog
    ion_tuples = list(itertools.permutations(eve_lines.columns.values, 2))
    ion_permutations = pd.Index([' by '.join(ion_tuples[i]) for i in range(len(ion_tuples))])

    jedi_row.set_index('Event #', inplace=True)
    jedi_row = jedi_row.join(pd.DataFrame(columns=eve_lines.columns + ' Pre-Flare Irradiance [W/m2]'))

    jedi_row = jedi_row.join(pd.DataFrame(columns=eve_lines.columns + ' Slope Start Time'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=eve_lines.columns + ' Slope End Time'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=eve_lines.columns + ' Slope Min [%/s]'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=eve_lines.columns + ' Slope Max [%/s]'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=eve_lines.columns + ' Slope Mean [%/s]'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=eve_lines.columns + ' Slope Uncertainty [%/s]'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=eve_lines.columns + ' Depth Time'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=eve_lines.columns + ' Depth [%]'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=eve_lines.columns + ' Depth Uncertainty [%]'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=eve_lines.columns + ' Duration Start Time'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=eve_lines.columns + ' Duration End Time'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=eve_lines.columns + ' Duration [s]'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=eve_lines.columns + ' Fitting Gamma'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=eve_lines.columns + ' Fitting Score'))

    jedi_row = jedi_row.join(pd.DataFrame(columns=ion_permutations + ' Slope Start Time'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=ion_permutations + ' Slope End Time'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=ion_permutations + ' Slope Min [%/s]'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=ion_permutations + ' Slope Max [%/s]'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=ion_permutations + ' Slope Mean [%/s]'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=ion_permutations + ' Slope Uncertainty [%/s]'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=ion_permutations + ' Depth Time'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=ion_permutations + ' Depth [%]'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=ion_permutations + ' Depth Uncertainty [%]'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=ion_permutations + ' Duration Start Time'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=ion_permutations + ' Duration End Time'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=ion_permutations + ' Duration [s]'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=ion_permutations + ' Correction Time Shift [s]'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=ion_permutations + ' Correction Scale Factor'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=ion_permutations + ' Fitting Gamma'))
    jedi_row = jedi_row.join(pd.DataFrame(columns=ion_permutations + ' Fitting Score'))

    # Start a new csv file on disk and return the jedi row dataframe
    jedi_row.to_csv(jedi_csv_filename, header=True, index=False, mode='w')
    return jedi_row




