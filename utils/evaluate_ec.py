"""
 this script takes as input:
 - the .ec_data file for a reference genome (processed by rust-mhdbg with min-abundance of 1)
 - the .ec_data file for a set of reads 
 - and optionnally,
   the .ec_data file for the same set of reads, processed differently (e.g. corrected)
 - and also optionnally,
   the .poa.ec_data file that contains which reads are retrieved for the template
 - and also optionnally,
   a maximum number of reads to display alignments for
 and outputs the needleman-wunch alignment of each read to the reference (semi-global aln)  
 and optionally outputs a comparison between the two set of reads (e.g. corrected vs uncorrected)
"""
import math
nb_processes = 2
max_nb_reads = 50

def parse_file(filename, only_those_reads = None, max_reads = None):
    if max_reads is None:
        max_reads = max_nb_reads
    res = []
    counter = 0
    seq_id = ""
    parsed_reads = set()
    for line in open(filename):
        if counter % 5 == 0:
            seq_id = line.strip()
            if len(res) <= max_reads:
                parsed_reads.add(seq_id)
        if counter % 5 != 2:
            counter += 1 
            continue
        spl = line.split()
        minims = list(map(int,spl))
        if only_those_reads is None or seq_id in only_those_reads:
            res += [(seq_id,minims)]
        counter += 1
        #if len(res) > max_reads: break
    return res, parsed_reads

# adapted from NW code here https://stackoverflow.com/questions/2718809/how-to-diff-align-python-lists-using-arbitrary-matching-function
# 
def semiglobal_align(a, b):
    # This is regular Needleman-Wunsch scoring.
    # which is not quite edit distance: match would need to be 0 for ED.
    # But i dunno how to compute semiglobal edit distance so i'll take that for now!
    replace_func = lambda x,y: 1 if x==y else -1
    insert = -1
    delete = -1

    #for traceback
    ZERO, LEFT, UP, DIAGONAL = 0, 1, 2, 3

    len_a = len(a)
    len_b = len(b)

    matrix = [[(0, ZERO) for x in range(len_b + 1)] for y in range(len_a + 1)]

    """
    #this is for NW
    for i in range(len_a + 1):
        matrix[i][0] = (insert * i, UP)

    for j in range(len_b + 1):
        matrix[0][j] = (delete * j, LEFT)
    """

    for i in range(1, len_a + 1):
        for j in range(1, len_b + 1):
            replace = replace_func(a[i - 1], b[j - 1])
            matrix[i][j] = max([
                (matrix[i - 1][j - 1][0] + replace, DIAGONAL),
                (matrix[i][j - 1][0] + insert, LEFT),
                (matrix[i - 1][j][0] + delete, UP)
            ])

    # find max score at end of read
    (best_i, best_j, best_score) = 0,0,0
    for i in range(1, len_a + 1):
        #for j in range(1, len_b + 1):
        j = len_b
        if matrix[i][j][0] > best_score:
            best_score = matrix[i][j][0]
            best_i, best_j = i,j
    #print("besti,j",best_i,best_j)
    i, j = best_i, best_j
    align_a = []
    align_b = []
    aln_str = ""

    nb_matches = 0
    nb_columns = 0
    # don't stop until reached beginning of query (or ref)
    while i > 0 and j > 0:
        nb_columns += 1
        if matrix[i][j][1] == DIAGONAL:
            align_a += [a[i - 1]]
            align_b += [b[j - 1]]
            if a[i - 1] == b[j - 1]: 
                nb_matches += 1 
                aln_str += "M"
            else:
                aln_str += "X"
            i -= 1
            j -= 1
        elif matrix[i][j][1] == LEFT:
            align_a += ["-"]
            align_b += [b[j - 1]]
            aln_str += "-"
            j -= 1
        else: # UP
            align_a += [a[i - 1]]
            align_b += ["-"]
            aln_str += "i"
            i -= 1
    
    blast_identity = 100.0 * nb_matches / nb_columns if nb_columns > 0 else 0
    return best_score, align_a[::-1], align_b[::-1], blast_identity, aln_str


from multiprocessing import Pool
from contextlib import closing # python/pypy 2 compat,  https://stackoverflow.com/questions/25968518/python-multiprocessing-lib-error-attributeerror-exit
import time

def align(arg):
    read_id, read = arg
    global reference
    fwd = semiglobal_align(reference,read)
    rev = semiglobal_align(reference,read[::-1])
    aln = rev if rev[0] > fwd[0] else fwd
    #time.sleep(0.0001)
    #aln=(0,[0],[0],0)
    aln_score = aln[0]
    # my old identity definiton was:
    #identity = ((100.0*aln_score)/(1.0*len(read)))
    # this is more of a score than an identity.
    # Will now compute BLAST identity, as per
    # https://lh3.github.io/2018/11/25/on-the-definition-of-sequence-identity
    # i.e. number of matches divided by number of columns
    identity = aln[3]
    #print(read,aln_score)
    #print("read identity: %.2f%%" % identity)
    return identity, aln, read_id, read

def process_reads(reads,filename, only_those_reads = None):
    id_dict = dict() # stores identities
    aln_dict = dict() # stores alignments
    orig_dict = dict() # stores original read 'sequences' (of minimizers)

    reads_to_align = [read for read in reads if only_those_reads is None or read[0] in only_those_reads] 

    with closing(Pool(nb_processes)) as p:
        aln_results = p.map(align,reads_to_align)

    for (identity, aln, read_id, read) in aln_results:
        id_dict[read_id] = identity
        aln_dict[read_id] = (aln[1],aln[2], aln[4])

    for read_id, minims in reads:
        orig_dict[read_id] = minims 

    identities = id_dict.values()
    if len(identities) == 0:
        mean_identity = 0
    else:
        mean_identity = sum(identities) / (1.0*len(identities))
    print("for",filename,"mean read identity: %.2f%%" % mean_identity)
    return id_dict, aln_dict, orig_dict

def short_name(read_id):
    max_len=25
    return read_id[:max_len]+".." if len(read_id) > max_len else read_id

def jac(poa_template,lst):
    mean_jac = 0
    nb_included = 0
    for poa_seq_id in lst:
        poa_r1 = set(orig_r1[poa_seq_id])
        mean_jac += len(poa_template & poa_r1) / len(poa_template | poa_r1)
        nb_included += 1
    if nb_included > 0:
        mean_jac /= nb_included
    return 1-mean_jac

def mash(poa_template,lst):
    mean_mash = 0
    nb_included = 0
    for poa_seq_id in lst:
        poa_r1 = set(orig_r1[poa_seq_id])
        jac = len(poa_template & poa_r1) / len(poa_template | poa_r1)
        if jac == 0.00: mean_mash += 1
        else: mean_mash += -1.0/10.0 * math.log((2.0 * jac) / (1.0 + jac))
        nb_included += 1
    if nb_included > 0:
        mean_mash /= nb_included
    return mean_mash


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3 or ".ec_data" not in sys.argv[2] or ".ec_data" not in sys.argv[1]:
        exit("input: <reference.ec_data> [reads.ec_data] [reads.corrected.ec_data] [reads.poa.ec_data]\n will evaluate accuracy of minimizers in reads\n")

    import evaluate_poa

    file1 = sys.argv[1]
    file2 = sys.argv[2]
    if len(sys.argv) > 3:
        file3 = sys.argv[3]
    if len(sys.argv) > 5:
        max_nb_reads = int(sys.argv[5])

    reference, osef          = parse_file(file1)
    assert(len(reference)==1)
    reads, only_those_reads  = parse_file(file2)
    reads2, osef             = parse_file(file3, only_those_reads) if len(sys.argv) > 3 else None

    print("loaded",len(reference),"reference, and",len(reads),"reads")

    if len(sys.argv) > 4:
        file_poa = sys.argv[4]
        poa_d, poa_d_itv, poa_reads = evaluate_poa.prepare_eval_poa(file_poa, only_those_reads)
    else:
        file_poa = None

    print("loaded",len(poa_d),"POA templates")



    reference = reference[0][1]


    print("about to process",len(reads),"reads")

    id_r1, aln_r1, orig_r1 = process_reads(reads, file2, only_those_reads)
    if reads2 is not None:
        id_r2, aln_r2, orig_r2 = process_reads(reads2, file3, only_those_reads)

    nb_better = 0
    nb_nochange = 0
    nb_worse  = 0
    for seq_id in id_r1:
        if seq_id in id_r2:
            ir1 = id_r1[seq_id]
            ir2 = id_r2[seq_id]
            print("read",short_name(seq_id),"uncor: %0.2f" % ir1,"cor: %0.2f" % ir2)
            if ir1 < ir2:
                nb_better += 1
            elif ir2 < ir1:
                nb_worse += 1
            else:
                nb_nochange += 1
        
            # poa & Jaccard stats
            if file_poa is not None:
                poa_template = set(orig_r1[seq_id])
                tp, fp, fn = evaluate_poa.eval_poa(seq_id, poa_d, poa_d_itv)
                print("POA retrieval TP: %d (Jac %.2f) (Mash %.2f)    FP: %d (Jac %.2f) (Mash %.2f)   FN: %d (Jac %.2f) (Mash %.2f)" \
                        % (len(tp),jac(poa_template,tp),mash(poa_template,tp),
                            len(fp),jac(poa_template,fp),mash(poa_template,fp),
                            len(fn),jac(poa_template,fn),mash(poa_template,fn)))

            debug_aln = True
            if debug_aln:
                print("alignment of uncorrected read",short_name(seq_id)," (len %d) to ref:" % len(orig_r1[seq_id]))
                #print(orig_r1[seq_id]) # print original read sequence of minimizers
                aln = aln_r1[seq_id]
                def pretty_print(x):
                    print("\t".join(map(lambda y:str(y)[:2],x)))
                #pretty_print(aln[0])
                #pretty_print(aln[1])
                print(aln[2])
                print("and now the corrected read (len %d) alignment:" % len(orig_r2[seq_id]))
                #print(orig_r2[seq_id])
                aln = aln_r2[seq_id]
                #pretty_print(aln[0])
                #pretty_print(aln[1])
                print(aln[2])

                print("---")

    print(nb_better,"reads improved")
    print(nb_nochange,"reads unchanged")
    print(nb_worse,"reads made worse")
