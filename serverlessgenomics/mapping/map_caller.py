import collections
import copy
import logging

from .alignment_mapper import gem_indexer_mapper, index_correction, filter_index_to_mpileup
from ..parameters import PipelineRun, Lithops

from ..stats import Stats

logger = logging.getLogger(__name__)

map1_cachefile = 'lithops_map1_checkpoint'
correction_cachefile = 'lithops_correction_checkpoint'
map2_cachefile = 'lithops_map2_checkpoint'


def generate_gem_indexer_mapper_iterdata(pipeline_params: PipelineRun, fasta_chunks, fastq_chunks):
    iterdata = []
    for fq_i, fq_ch in enumerate(fastq_chunks):
        if (pipeline_params.fastq_chunk_range is None) or (fq_i in pipeline_params.fastq_chunk_range):
            for fa_i, fa_ch in enumerate(fasta_chunks):
                params = {'pipeline_params': pipeline_params,
                        'fasta_chunk_id': fa_i, 'fasta_chunk': fa_ch,
                        'fastq_chunk': fq_ch, 'fastq_chunk_id': fq_i}
                iterdata.append(params)
    return iterdata


def generate_index_correction_iterdata(pipeline_params, gem_mapper_output):
    # Group gem mapper output by fastq chunk id
    fq_groups = collections.defaultdict(list)
    for fq, _, map_key, _ in gem_mapper_output:
        fq_groups[fq].append(map_key)

    iterdata = [{'pipeline_params': pipeline_params,
                 'fastq_chunk_id': fq_id,
                 'map_index_keys': map_keys} for fq_id, map_keys in fq_groups.items()]
    
    return iterdata


def generate_index_to_mpileup_iterdata(pipeline_params, fasta_chunks, fastq_chunks, gem_mapper_output,
                                       corrected_indexes):
    iterdata = []

    # Convert corrected index output (list of tuples) to sorted list by fastq chunk id
    corrected_indexes_fq = [tup[1] for tup in sorted(corrected_indexes, key=lambda tup: tup[0])]

    for fq_i, fa_i, _, filter_map_index in gem_mapper_output:
        iterdata.append({'pipeline_params': pipeline_params,
                         'fasta_chunk_id': fa_i,
                         'fasta_chunk': fasta_chunks[fa_i],
                         'fastq_chunk_id': fq_i,
                         'fastq_chunk': fastq_chunks[fq_i],
                         'filtered_map_key': filter_map_index,
                         'corrected_index_key': corrected_indexes_fq[fq_i]})

    return iterdata


def split_data_result(result):
    aux_timer = []
    aux_info = []
    for info, timer in result:
        aux_info.append(info)
        aux_timer.append(timer)
    return aux_info, aux_timer

def run_full_alignment(pipeline_params: PipelineRun, lithops: Lithops, fasta_chunks, fastq_chunks):
    """
    Execute the map phase

    Args:
        pipeline_params (PipelineRun): pipeline arguments
        alignment_batches (list): iterdata generated in the preprocessing stage
        map_func (AlignmentMapper): class containing the map functions
        num_chunks (int): number of corrections needed

    Returns:
        float: time taken to execute this phase
    """
    # MAP: Stage 1
    # TODO guardar tamaño de datos con los que se juega
    
    subStat = Stats()
    logger.debug("PROCESSING MAP: STAGE 1")    
    subStat.timer_start('gem_indexer_mapper')   
    iterdata = generate_gem_indexer_mapper_iterdata(pipeline_params, fasta_chunks, fastq_chunks)
    gem_indexer_mapper_result = lithops.invoker.map(gem_indexer_mapper, iterdata)  
    subStat.timer_stop('gem_indexer_mapper')
    gem_indexer_mapper_result, timers = split_data_result(gem_indexer_mapper_result)
    subStat.store_dictio(timers, "subprocesses", "gem_indexer_mapper")
    
    # MAP: Index correction
    logger.debug("PROCESSING INDEX CORRECTION") 
    subStat.timer_start('index_correction')  
    iterdata = generate_index_correction_iterdata(pipeline_params, gem_indexer_mapper_result)
    index_correction_result = lithops.invoker.map(index_correction, iterdata)
    subStat.timer_stop('index_correction')  
    index_correction_result, timers = split_data_result(index_correction_result)
    subStat.store_dictio(timers, "subprocesses", "index_correction")

    # Map: Stage 2
    logger.debug("PROCESSING MAP: STAGE 2") 
    subStat.timer_start('filter_index_to_mpileup')  
    iterdata = generate_index_to_mpileup_iterdata(pipeline_params, fasta_chunks, fastq_chunks,
                                                  gem_indexer_mapper_result, index_correction_result)
    alignment_output = lithops.invoker.map(filter_index_to_mpileup, iterdata)
    subStat.timer_stop('filter_index_to_mpileup')  
    alignment_output, timers = split_data_result(alignment_output)
    subStat.store_dictio(timers, "subprocesses", "filter_index_to_mpileup")

    return alignment_output, subStat