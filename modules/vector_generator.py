# coding=utf-8
# ! /usr/bin/env python3.4

"""
MIT License

Copyright (c) 2018 NLX-Group

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

This code creates a summary over the data file and creates a matrix over the connecteions
    -- word_extractor(): creates a summary over the data file
    -- pMatrix_builder(): creates the matrix based on the relations among the extracted words and their synsets


Chakaveh.saedi@di.fc.ul.pt
"""

import os
import sys
import gc
import math
import random
import time
import json

from progressbar import ProgressBar, Percentage, Bar

from nltk.corpus import wordnet as wn

from modules.input_output import *

import numpy as np
from scipy.sparse import lil_matrix
from scipy.sparse import csr_matrix
from scipy.sparse import coo_matrix

from scipy.sparse.linalg import inv as inv_sparse
from numpy.linalg import inv as inv_dense
from scipy.linalg import inv as inv_scipy
# from sklearn.utils.testing import assert_array_almost_equal
from sklearn import random_projection

import sklearn.preprocessing as preprocessing
from sklearn.decomposition import PCA as PCA_sklearn
from sklearn.decomposition import IncrementalPCA as inc_PCA_sklearn
from sklearn.decomposition import KernelPCA as kernel_PCA_sklearn
from sklearn.manifold import Isomap  as isopam_sklearn

from keras.models import load_model
from keras import backend as K
from keras.models import Sequential, Model
from keras.layers import Input, Dense, Activation
from keras import regularizers
from keras.optimizers import RMSprop


# -----------------------------

def word_extractor(all_pos, all_data, only_one_word, only_once, log):
    # NOTE: all_data = [key:synsetWrds(list), synsetConnections(list), synsetRelationTypes(list), connectedSynsetPos(list), gloss],offset_list
    start_time = time.time()
    word_set = set()  # Note: w1offset(w1)'\t'offset(w1)'\t'pos(w1) # ch???a danh s??ch c??c offset
    words_wrdcnt = {}  # Note: wi:cnt(wi)
    synset_wrd = {}  # a dictionary showing each word belongs to which synset {synset_pos:w1, w2, ...}

    for pos in all_pos:
        this_file_offsets = all_data[pos][1]  # get the list of offset
        for offset in this_file_offsets:
            this_syn_wrd_cnt = len(all_data[pos][0][offset][0])  # get the length of list of word in synset
            new_wrd = False
            indx = 0
            while new_wrd != True and indx < this_syn_wrd_cnt:
                this_syn_wrd = all_data[pos][0][offset][0][indx]  # l???y c??c t??? trong synset ra
                if this_syn_wrd not in words_wrdcnt.keys():  # ??? ????y m??nh c?? th??? hi???u l?? ??ang th???ng k?? s??? ngh??a c?? th??? c?? c???a 1 t??? t????ng ???ng b???ng dict ??
                    words_wrdcnt.update({this_syn_wrd: 1})
                else:
                    words_wrdcnt[this_syn_wrd] += 1

                lex_id = all_data[pos][0][offset][5][indx]
                indx += 1
                key = offset + "_" + pos
                if only_once:  # h??nh nh?? l?? v???i m???i t??? ch??? l???y 1 ngh??a duy nh???t c???a t??? ????
                    if words_wrdcnt[this_syn_wrd] == 1:  # ki???m tra n???u t??? n??y ch??? c?? 1 ngh??a
                        word_set.add(this_syn_wrd + "_offset" + str(offset) + "\t" + str(offset) + "\t" + pos)
                        synset_wrd.update(
                            {key: [this_syn_wrd + "_offset" + str(offset) + "\t" + str(offset) + "\t" + pos]})
                else:  # c??ch x??? l?? v???i 1 t??? nhi???u ngh??a, thu???c 1 synset n??o th?? l??u th??ng tin t??? ???? ???ng v???i synset ???? lu??n
                    word_set.add(this_syn_wrd + "_offset" + str(offset) + "\t" + str(
                        offset) + "\t" + pos + '\t' + lex_id)  # l??u l???i th??ng tin c???a 1 word
                    if key not in synset_wrd.keys():
                        synset_wrd.update({key: [this_syn_wrd + "_offset" + str(offset) + "\t" + str(
                            offset) + "\t" + pos + "\t" + lex_id]})  # l??u l???i th??ng tin c??c word trong 1 synset
                    else:
                        synset_wrd[key].append(this_syn_wrd + "_offset" + str(offset) + "\t" + str(offset) + "\t" + pos + "\t" + lex_id)

                if only_one_word:  # n???u m???i synset ch??? l???y 1 t??? th?? tho??t kh???i v??ng l???p
                    new_wrd = True

    finish_time = time.time()
    print("    %d different senses are extracted. (%d ambiguous words were found)" % (
    len(word_set), len([val for key, val in words_wrdcnt.items() if val > 1])))
    log.write("    %d words in different senses were extracted  in  %.3f seconds \n" % (
    len(word_set), finish_time - start_time))

    return sorted(word_set), synset_wrd


def pMatrix_builder(all_data, all_pos, word_set, synset_wrd, equal_weight, approach, for_WSD, accepted_rel, to_keep,
                    log, main_path, lang):
    start_time = time.time()
    print("\n* Creating the relation matrix")
    log.write("\n* Creating the relation matrix")
    word_list = list(word_set)

    word_indx = {}  # Note: a dictionary showing the index for each word in the matrix  {word:index}
    synonym_index = set()  # a set containg tuples of indexes of words that are synonyms
    w_indx = 0

    weights = {"!": 1, "~": 1, "~i": 1, "@": 1, "@i": 1, "%m": .8, "%s": .8, "%p": .8, "#m": .8, "#s": .8,
               "#p": .8}  # sao l???i ????nh tr???ng s??? nh?? v???y ta
    # !: Antonym(tr??i ngh??a) ~: Hyponym(h??? danh) ~i: Instance hyponym @: Hypernym(Th?????ng danh) @i: instance hypernym
    # %m: member meronym(b??? ph???n) %s: substance meronym %p: Part meronym ...
    # T???i sao b??? ph???n v?? bao h??m th?? ????nh tr???ng s??? l?? 0.8 c??n th?????ng danh h??? danh n??y kia th?? l?? 1.

    for i in range(len(word_list)):  # ??o???n code n??y th?? ch??? mu???n t???o index c???a m???i t??? th??i
        parts = word_list[i].split("\t")

        if for_WSD:
            word_indx.update({parts[0]: w_indx})
            w_indx += 1
        else:
            if word_list[i].split("_offset")[0] not in word_indx.keys():
                word_indx.update({word_list[i].split("_offset")[0]: w_indx})
                w_indx += 1

    dim = (len(word_indx), len(word_indx))  # m?? sao n?? code nh??n t???n chi ph?? d??? v???y ta
    print("    Matrix dimension is %d x %d" % (dim[0], dim[1]))

    # ch???t ??? ch??? n??y n??, kh??ng ????? v??ng nh??? c???p ph??t
    p_matrix = np.zeros(dim, dtype=np.float16)
    # p_matrix = np.zeros(dim)

    pbar = ProgressBar(widgets=[Percentage(), Bar()],
                       maxval=len(word_list))  # show thanh ti???n tr??nh ch???y ???????c bao nhi??u % r???i
    for i in pbar(range(len(word_list))):
        parts = word_list[i].split("\t")
        if for_WSD:
            cur_wrd = parts[0]
        else:
            cur_wrd = word_list[i].split("_offset")[0]
        cur_synset = parts[1]  # l???y synset id
        cur_pos = parts[2]  # l???y pos
        cur_wrd_indx = word_indx[cur_wrd]  # lay id cua word

        target_cnt = len(all_data[cur_pos][0][cur_synset][1])  # s??? l?????ng synset m?? n?? tr??? t???i
        target_synsets_relation = all_data[cur_pos][0][cur_synset][2]  # danh s??ch c??c con tr???
        target_synsets_pos = all_data[cur_pos][0][cur_synset][3]  # danh s??ch c??c pos c???a c??c synset m?? n?? tr??? t???i
        target_synsets = all_data[cur_pos][0][cur_synset][1]  # l???y danh s??ch c??c synset kh??c m?? n?? tr??? t???i
        # To avoid self-loops
        while cur_synset in target_synsets:  # ch??a hi???u l???m context n??y
            target_synsets.remove(cur_synset)

        # m???i ?????u m??nh l???y 1 t??? ra v?? d?? l???i synset ch???a n??, r???i b???t c???p index c???a t??? ???? v???i t???ng t??? trong synset ch???a n??
        if "syn" in accepted_rel:
            cur_synset_words = synset_wrd[parts[1] + "_" + parts[2]]  # l???y ra danh s??ch c??c t??? thu???c synset ????
            if len(cur_synset_words) > 1:
                for cur_synset_word in cur_synset_words:
                    if not for_WSD:
                        wrd = cur_synset_word.split("_offset")[0]
                    if wrd != cur_wrd:
                        syn_wrd_indx = word_indx[wrd]
                        synonym_index.add((cur_wrd_indx,
                                           syn_wrd_indx))  # l??u th??ng tin c???p t??? hi???n t???i v?? t??? ?????ng ngh??a v???i n?? trong c??ng synset

        # N???u s??? l?????ng synset m?? synset hi???n t???i tr??? t???i l???n h??n 0
        # ??? b?????c n??y m??nh ??ang t??m m???i quan h??? gi???a t??? hi???n t???i v???i t???t c??? c??c t??? thu???c c??c synset m?? c?? m???i quan h??? v???i synset ch???a t??? hi???n t???i.
        if target_cnt != 0:
            for j in range(len(target_synsets)):
                if target_synsets_pos[j] in all_pos:
                    if "all" in accepted_rel or target_synsets_relation[j] in accepted_rel:
                        key = target_synsets[j] + "_" + target_synsets_pos[j]
                        if key in synset_wrd.keys():
                            target_wrds = synset_wrd[key]  # l???y ra danh s??ch c??c t??? thu???c synset n??y
                            for target_wrd in target_wrds:
                                if not for_WSD:
                                    target_wrd = target_wrd.split("_offset")[0]
                                if target_wrd != cur_wrd:  # x??t c??c t??? kh??c cur_word thu???c c??c synset c?? m???i quan h??? v???i synset ch???a cur_word
                                    target_wrd_indx = word_indx[target_wrd]
                                    if equal_weight:
                                        weight = 1
                                    else:
                                        if target_synsets_relation[j] in weights.keys():
                                            weight = weights[target_synsets_relation[j]]
                                        else:
                                            weight = .5
                                    p_matrix[
                                        cur_wrd_indx, target_wrd_indx] += weight  # l??u l???i m???i quan h??? gi???a t??? hi???n t???i v?? t??? kh??c trong c??c synset c?? m???i quan h??? v???i n??.
                                    # ??? ????y m??nh ch??? s??? l?? b?????c n??y h??? d??ng += ?? l?? kh??ng bi???t l?? c?? g???p l???i ph???i tr?????ng h???p c???ng d???n n??o ??? ????y kh??ng, v?? 1 t??? th?? c?? nhi???u ngh??a v?? c??
                                    # th??? cur_word ??? ngh??a n??y b???t c???p v???i t??? cat, l??c n??y t??? cat c?? ngh??a l?? m??o ??i. R???i v???n cur_word l???i ??? 1 synset kh??c v???n b???t c???p v???i t??? cat c?? ngh??a l?? cho ch???ng h???n.
                                    # m??nh kh??ng ch???ng minh ???????c l?? kh??ng th??? x???y ra, n??n ch???c ph???i code an to??n ch??? n??y. n??n ph???i d??ng dict r???i
                        # else:
                        #    print ("the word '%s' whith pos '%s' was not found in synset_wrd dictionary" % (target_wrd, target_synsets_pos[j]))
                        # NOTE: this only happens for ambiguous words and when only one sense of them is selected.
        # else:
        #     print("No target for " + str(cur_synset))

    # handling synonymy
    # ri??ng c??c t??? m?? n???m trong c??ng synset v???i t??? hi???n t???i th?? ch???c ch???n weight =1
    if approach == 1 and "syn" in accepted_rel:
        for itm in synonym_index:
            p_matrix[itm[0], itm[1]] = 1.0

    # handling association relations
    """
    new_arcs = 0
    updated_arcs = 0
    not_found = set()

    if lang == "English":
        with open(main_path + "cue_res_inEng.json", "r") as fp:
            cue_res = json.load(fp)
    else:
        with open(main_path + "cue_res_inDutch_final.json", "r") as fp:
            cue_res = json.load(fp)    

    for cue_wrd in cue_res.keys():
        try:
            cue_wrd_indx = word_indx[cur_wrd]
        except:
            not_found.add(cur_wrd)
            continue
        for resp_wrd in cue_res[cue_wrd].keys():
            if resp_wrd in word_indx.keys():
                res_wrd_indx = word_indx[resp_wrd]
                if cue_wrd_indx != res_wrd_indx:
                    if p_matrix[cur_wrd_indx, res_wrd_indx] == 0:
                        new_arcs += 1
                    else:
                        updated_arcs += 1
                    p_matrix[cur_wrd_indx, res_wrd_indx] += cue_res[cue_wrd][resp_wrd]
            else:
                not_found.add(resp_wrd)
    print("the association data is inserted into the wordnet graph. New arcs= ", new_arcs, " updated arcs= ",updated_arcs, " not_found= ", len(not_found))
    """

    finish_time = time.time()
    print("    Relation matrix is created")
    log.write("\n    Relation matrix was created in %.3f seconds\n" % (finish_time - start_time))

    # to check the number of non-zero elements in the p matrix
    print("    Checking the number of non-zero elements in relation matrix")
    # non_zero = len(p_matrix[np.nonzero(p_matrix)])
    non_zero = -10

    print("        %d elements out of %d elements are non-zero" % (non_zero, len(p_matrix) * len(p_matrix)))
    log.write("        %d elements out of %d elements are non-zero\n" % (non_zero, len(p_matrix) * len(p_matrix)))

    if for_WSD:
        return p_matrix, dim, word_list, non_zero  # Code is not Complete YET -> word_list must be edited
    else:
        word_list = []
        temp = sorted(word_indx.items(), key=lambda x: x[1])  # tra ve tuple
        for itm in temp:
            word_list.append(itm[0])
        if to_keep != "all":  # N???u kh??c string th?? n?? ph???i l?? s??? m???i ??p ki???u int ???????c nh??
            # ??? ????y l?? c?? gi???m s??? l?????ng t??? c???a m??nh xu???ng ch??? c??n 60000 nh??
            p_matrix, word_list, synonym_index = sort_rem(p_matrix, word_list, synonym_index, int(to_keep), lang)
            dim = (len(word_list), len(word_list))
        print("************Number of words are %d after the cut" % (len(word_list)))
        return p_matrix, dim, word_list, non_zero, np.array(list(synonym_index))


def my_pMatrix_builder(all_data, all_pos, word_set, synset_wrd, equal_weight, approach, for_WSD, accepted_rel, to_keep,
                       log, main_path, lang, sense_number_per_word):
    start_time = time.time()
    print("\n* Creating the relation matrix")
    log.write("\n* Creating the relation matrix")
    word_list = list(word_set)

    word_indx = {}  # Note: a dictionary showing the index for each word in the matrix  {word:index}
    synonym_index = set()  # a set containg tuples of indexes of words that are synonyms
    w_indx = 0

    weights = {"!": 1, "~": 1, "~i": 1, "@": 1, "@i": 1, "%m": .8, "%s": .8, "%p": .8, "#m": .8, "#s": .8,
               "#p": .8}  # sao l???i ????nh tr???ng s??? nh?? v???y ta
    # !: Antonym(tr??i ngh??a) ~: Hyponym(h??? danh) ~i: Instance hyponym @: Hypernym(Th?????ng danh) @i: instance hypernym
    # %m: member meronym(b??? ph???n) %s: substance meronym %p: Part meronym ...
    # T???i sao b??? ph???n v?? bao h??m th?? ????nh tr???ng s??? l?? 0.8 c??n th?????ng danh h??? danh n??y kia th?? l?? 1.

    for i in range(len(word_list)):  # ??o???n code n??y th?? ch??? mu???n t???o index c???a m???i t??? th??i
        parts = word_list[i].split("\t")

        if for_WSD:
            word_indx.update({parts[0]: w_indx})
            w_indx += 1
        else:
            if word_list[i].split("_offset")[0] not in word_indx.keys():
                word_indx.update({word_list[i].split("_offset")[0]: w_indx})
                w_indx += 1

    dim = (len(word_indx), len(word_indx))  # m?? sao n?? code nh??n t???n chi ph?? d??? v???y ta
    print("    Matrix dimension is %d x %d" % (dim[0], dim[1]))

    # ch???t ??? ch??? n??y n??, kh??ng ????? v??ng nh??? c???p ph??t
    sparse_matrix = {}
    # p_matrix = np.zeros(dim)

    pbar = ProgressBar(widgets=[Percentage(), Bar()],
                       maxval=len(word_list))  # show thanh ti???n tr??nh ch???y ???????c bao nhi??u % r???i

    count=0
    sum_all=0
    for i in pbar(range(len(word_list))):
        parts = word_list[i].split("\t")
        if for_WSD:
            cur_wrd = parts[0]
        else:
            cur_wrd = word_list[i].split("_offset")[0]
        cur_synset = parts[1]  # l???y synset id
        cur_pos = parts[2]  # l???y pos
        cur_offset = parts[1]
        key = f'{cur_wrd.lower()}_{cur_offset}'
        try:
            cur_sense_number = sense_number_per_word[f'{cur_wrd.lower()}_{cur_offset}']
        except:
            continue
        cur_wrd_indx = word_indx[cur_wrd]  # lay id cua word

        target_cnt = len(all_data[cur_pos][0][cur_synset][1])  # s??? l?????ng synset m?? n?? tr??? t???i
        target_synsets_relation = all_data[cur_pos][0][cur_synset][2]  # danh s??ch c??c con tr???
        target_synsets_pos = all_data[cur_pos][0][cur_synset][3]  # danh s??ch c??c pos c???a c??c synset m?? n?? tr??? t???i
        target_synsets = all_data[cur_pos][0][cur_synset][1]  # l???y danh s??ch c??c synset kh??c m?? n?? tr??? t???i
        # To avoid self-loops
        while cur_synset in target_synsets:  # ch??a hi???u l???m context n??y
            target_synsets.remove(cur_synset)

        # m???i ?????u m??nh l???y 1 t??? ra v?? d?? l???i synset ch???a n??, r???i b???t c???p index c???a t??? ???? v???i t???ng t??? trong synset ch???a n??
        if "syn" in accepted_rel:
            cur_synset_words = synset_wrd[parts[1] + "_" + parts[2]]  # l???y ra danh s??ch c??c t??? thu???c synset ????
            if len(cur_synset_words) > 1:
                for cur_synset_word in cur_synset_words:
                    if not for_WSD:
                        wrd = cur_synset_word.split("_offset")[0]
                    if wrd != cur_wrd:
                        syn_wrd_indx = word_indx[wrd]
                        synonym_index.add((cur_wrd_indx,
                                           syn_wrd_indx))  # l??u th??ng tin c???p t??? hi???n t???i v?? t??? ?????ng ngh??a v???i n?? trong c??ng synset

        # N???u s??? l?????ng synset m?? synset hi???n t???i tr??? t???i l???n h??n 0
        # ??? b?????c n??y m??nh ??ang t??m m???i quan h??? gi???a t??? hi???n t???i v???i t???t c??? c??c t??? thu???c c??c synset m?? c?? m???i quan h??? v???i synset ch???a t??? hi???n t???i.
        if target_cnt != 0:
            for j in range(len(target_synsets)):
                if target_synsets_pos[j] in all_pos:
                    if "all" in accepted_rel or target_synsets_relation[j] in accepted_rel:
                        key = target_synsets[j] + "_" + target_synsets_pos[j]
                        if key in synset_wrd.keys():
                            ls_target_wrds = synset_wrd[key]  # l???y ra danh s??ch c??c t??? thu???c synset n??y
                            for target_part in ls_target_wrds:
                                target_parts = target_part.split('\t')
                                target_wrd=target_parts[0]
                                if not for_WSD:
                                    target_wrd = target_part.split("_offset")[0]
                                if target_wrd != cur_wrd:  # x??t c??c t??? kh??c cur_word thu???c c??c synset c?? m???i quan h??? v???i synset ch???a cur_word
                                    sum_all+=1
                                    target_wrd_indx = word_indx[target_wrd]
                                    target_offset = target_parts[1]
                                    target_pos = target_parts[2]
                                    try:
                                        target_sense_number = sense_number_per_word[f'{target_wrd.lower()}_{target_offset}']
                                        synset_cur_wrd = wn.synset(f'{cur_wrd}.{cur_pos}.{cur_sense_number}')
                                        synset_target_wrd = wn.synset(f'{target_wrd}.{target_pos}.{target_sense_number}')
                                        weight = synset_cur_wrd.path_similarity(synset_target_wrd)
                                    except Exception as e:
                                        print("Error: ", e)
                                        weight=np.random.uniform(0, 0.001)

                                    if weight==None:
                                        weight=0
                                        count+=1
                                        # print(synset_cur_wrd, " ", synset_target_wrd)

                                    sparse_matrix[(cur_wrd_indx, target_wrd_indx)] = sparse_matrix.setdefault(
                                        (cur_wrd_indx, target_wrd_indx), 0) + weight
                        # else:
                        #    print ("the word '%s' whith pos '%s' was not found in synset_wrd dictionary" % (target_wrd, target_synsets_pos[j]))
                        # NOTE: this only happens for ambiguous words and when only one sense of them is selected.
        # else:
        #     print("No target for " + str(cur_synset))
    print('Gia tri bien count : ', count)
    print("Gia tri bien sum_all: ", sum_all)
    # handling synonymy
    # ri??ng c??c t??? m?? n???m trong c??ng synset v???i t??? hi???n t???i th?? ch???c ch???n weight =1
    if approach == 1 and "syn" in accepted_rel:
        for itm in synonym_index:
            sparse_matrix[(itm[0], itm[1])] = 1.0

    # handling association relations
    """
    new_arcs = 0
    updated_arcs = 0
    not_found = set()

    if lang == "English":
        with open(main_path + "cue_res_inEng.json", "r") as fp:
            cue_res = json.load(fp)
    else:
        with open(main_path + "cue_res_inDutch_final.json", "r") as fp:
            cue_res = json.load(fp)    

    for cue_wrd in cue_res.keys():
        try:
            cue_wrd_indx = word_indx[cur_wrd]
        except:
            not_found.add(cur_wrd)
            continue
        for resp_wrd in cue_res[cue_wrd].keys():
            if resp_wrd in word_indx.keys():
                res_wrd_indx = word_indx[resp_wrd]
                if cue_wrd_indx != res_wrd_indx:
                    if p_matrix[cur_wrd_indx, res_wrd_indx] == 0:
                        new_arcs += 1
                    else:
                        updated_arcs += 1
                    p_matrix[cur_wrd_indx, res_wrd_indx] += cue_res[cue_wrd][resp_wrd]
            else:
                not_found.add(resp_wrd)
    print("the association data is inserted into the wordnet graph. New arcs= ", new_arcs, " updated arcs= ",updated_arcs, " not_found= ", len(not_found))
    """

    finish_time = time.time()
    print("    Relation matrix is created")
    log.write("\n    Relation matrix was created in %.3f seconds\n" % (finish_time - start_time))

    # to check the number of non-zero elements in the p matrix
    print("    Checking the number of non-zero elements in relation matrix")
    # non_zero = len(p_matrix[np.nonzero(p_matrix)])
    non_zero = -10

    if for_WSD:  # c??ng ch??a bi???t x??? l?? ??? ????y nh?? th??? n??o
        return sparse_matrix, dim, word_list, non_zero  # Code is not Complete YET -> word_list must be edited
    else:
        word_list = list(word_indx.keys())
        if to_keep != "all":  # N???u kh??c string th?? n?? ph???i l?? s??? m???i ??p ki???u int ???????c nh??
            # ??? ????y l?? c?? gi???m s??? l?????ng t??? c???a m??nh xu???ng ch??? c??n 60000 nh??
            sparse_matrix, word_list, synonym_index = my_sort_rem(sparse_matrix, word_list, synonym_index, int(to_keep),
                                                                  lang, dim[0])
            dim = (len(word_list), len(word_list))
            p_matrix = contruct_matrix_from_coo_format(sparse_matrix, dim)
        print("************Number of words are %d after the cut" % (len(word_list)))
        return p_matrix, dim, word_list, non_zero, np.array(list(synonym_index))


def sense_number_extractor(file_name):
    path = os.getcwd() + '/data/'
    fl = open(path + file_name)
    src = fl.readlines()
    fl.close()
    sense_number_per_word = {}
    for i in range(len(src)):
        line = src[i].strip()
        parts = line.split(" ")
        offset_id = parts[1]
        sense_number = parts[2]
        wrd = line.split("%")[0]
        sense_number_per_word[f'{wrd}_{offset_id}'] = int(sense_number)

    return sense_number_per_word


def contruct_matrix_from_coo_format(sparse_matrix, dim):
    p_matrix = np.zeros(dim, dtype=np.float16)
    for k, v in sparse_matrix.items():
        p_matrix[k[0], k[1]] = v

    return p_matrix


def random_walk(p_matrix, dim, iter, log, from_file, stage, PMI_coef, main_path):  # ???n s???
    if not from_file:
        if iter == "infinite":
            model = "the matrix inverse"
        else:
            model = iter + " iterations"
        print("\n* Random walk on the relations using %s " % (model))
        log.write("\n* Random walk on the relations using %s iteration\n" % (iter))

        alpha = 0.75

        start_time = time.time()
        if iter == "infinite":
            print("    Normalizing the relation matrix ... ")
            # print(np.isfinite(np.asanyarray(p_matrix)).all())
            p_matrix = preprocessing.normalize(p_matrix, norm='l1')  # m??nh cho norm='l2' ???????c kh??ng ta?
            p_matrix = np.array(p_matrix,
                                dtype="float16")  # b??? l???i v??ng nh??? ch??? n??y n??, t??? nhi??n l???i xin c???p ph??t 1 v??ng nh??? t????ng t??? n???a
            array_writer(p_matrix, "p_matrix", "bin", main_path)

            # to solve the singular matrix problem
            print(
                "    Adding very small random values in the matrix so it is not a singular matrix")  # singular matrix l?? g?? qu??n r ta
            random.seed(7)
            for i in range(dim[0] - 1):
                if np.random.rand() > .5:
                    p_matrix[i, i] += random.uniform(0, 0.00001)
                else:
                    p_matrix[i, i] -= random.uniform(0, 0.00001)

            print("    Random walk begins - matrix inverse calculation might take long")
            # Grw = (I - alpha*P)^-1

            # V???y v???n ????? v??ng nh??? ??? ????y l?? do xin c???p th??m 1 v??ng nh??? t????ng t??? nh?? v???y h??? ta.
            g_rw = inv_dense(np.identity(dim[0], dtype=np.float32) - (
                        alpha * p_matrix))  # causes memory problem # h??i v???y -----------------------
            # g_rw = inv_dense(np.identity(dim[0]) - (alpha * p_matrix))      # causes memory problem

        else:
            print("    Random walk begins - matrix multiplication might take long")
            print("    Normalizing the relation matrix ... ")
            p_matrix = preprocessing.normalize(p_matrix, norm='l1')

            # Grm_r = alpha^r*P^r + Grw_(r_1)
            G_last = np.identity(dim[0], dtype=np.float16)  # initializing G0
            alp_itr = alpha
            p_matrix_itr = p_matrix
            pbar = ProgressBar(widgets=[Percentage(), Bar()], maxval=int(iter))
            for i in pbar(range(int(iter))):
                s = time.time()
                g_rw = alp_itr * p_matrix_itr + G_last
                G_last = g_rw
                alp_itr *= alpha
                p_matrix_itr = np.dot(p_matrix_itr, p_matrix)
                f = time.time()
                print("iteration %d takes %s seconds" % (i + 1, str(round(f - s))))

            del (p_matrix_itr)

        finish_time = time.time()
        print("        Graph of random walk is created")
        log.write("    Graph of random walk was created in %.3f seconds\n" % (finish_time - start_time))
        del (p_matrix)
        gc.collect()

        array_writer(g_rw, "random_walk", "bin", main_path)

        # to check the number of non-zero elements after the random walk
        print("    Checking the number of non-zero elements in random walk matrix")
        # non_zero = len(g_rw[np.nonzero(g_rw)])
        non_zero = -10
        print("        %d elements out of %d elements are non-zero after the random walk" % (non_zero, dim[0] * dim[0]))
        log.write(
            "    %d elements out of %d elements are non-zero after the random walk\n" % (non_zero, dim[0] * dim[0]))

    else:
        if stage == "random_walk":
            print("\n* Reading graph of random walk from the previous run")
            log.write("\n* Reading graph of random walk from the previous run")
            g_rw = array_loader(stage, main_path)

    if not from_file or (from_file and stage == "random_walk"):
        # PMI calculation
        # PMI(Mij) = dim[0] x (Mij)/(Sum(elements in column j))
        print("\n* Calculating PMI+")
        log.write("\n* Calculating PMI+\n")

        # max(0,log [G(x|y)/G(x123...n)])
        start_time = time.time()
        col_sum = np.sum(g_rw, axis=0)  # sum of each column
        col_sum[col_sum == 0.0] = random.uniform(0, 0.0000001)

        # g_rw must be multiplied by a number [PMI_coef] otherwise the PMI result will be 0 for all elements
        # PMI_coef is the number of words in the main paper
        PMI_coef = dim[0]

        # an experiment on PMI_coef
        """
        digit = 0
        while PMI_coef > 10:
            PMI_coef /= 10
            digit += 1
        PMI_coef = int(math.pow(10,digit))
        """
        # m???i ?? trong ma tr???n g_rw th?? m??nh c?? th??? h???i l?? x??c xu???t ?????ng xu???t hi???n c???a 2 t??? ???? ?
        g_rw *= PMI_coef  # n???u nh??n cho t???ng h??ng th?? m??nh s??? ra ???????c k?? v???ng s??? l???n ?????ng xu???t hi???n c???a 2 t??? t????ng ???ng ????ng kh??ng ta?
        pbar = ProgressBar(widgets=[Percentage(), Bar()], maxval=dim[0])
        # for i in pbar(range(dim[0])): # m???y c??ch vi???t n??y v?? c??ng d???ng c???a pbar h??nh nh?? gi???ng v???i pdtm l?? ch??? ????? m??nh bi???t ti???n h??nh ???? th???c hi???n ???????c bao nhi??u ph???n tr??m.
        #     denominator = col_sum[i]
        #     for j in range(dim[1]):
        #         element = float(g_rw[i,j])/denominator  # H??nh nh?? c??ng th???c c?? g?? ???? sai sai, sao n??i l?? chia cho sum c???a c???t th??? j m??. C??i n??y th?? x??t m???c ?????nh l?? chia cho sum c???a c???t th??? i r???i.
        #         if element <= 1:                            # N???u mu???n s???a th?? ph???i ?????i th??? t??? v??ng l???p ????ng kh??ng?
        #             g_rw[i, j] = 0
        #         else:
        #             g_rw[i, j] = math.log(element, 2)

        # C???i thi???n t???c ????? t??nh to??n c???a code b???ng numpy v?? vi???t l???i cho ????ng theo c??ng th???c h??? ghi tr??n kia.
        for j in pbar(range(dim[1])):
            denominator = col_sum[j]
            g_rw[:, j] = g_rw[:, j] / denominator
            g_rw[g_rw[:, j] <= 1, j] = 0
            if len(g_rw[:, j] > 1) > 0:
                g_rw[g_rw[:, j] > 1, j] = np.log2(g_rw[g_rw[:, j] > 1, j])

        finish_time = time.time()

        print("    PMI+ is created")
        log.write("    PMI+ was created in %.3f seconds\n" % (finish_time - start_time))

        array_writer(g_rw, "PMI", "bin", main_path)

        print("    Checking the number of non-zero elements in PMI matrix")
        # non_zero = len(g_rw[np.nonzero(g_rw)])
        non_zero = -10
        print("        %d elements out of %d elements are non-zero in PMI matrix" % (non_zero, dim[0] * dim[0]))
        log.write("    %d elements out of %d elements are non-zero in PMI matrix\n" % (non_zero, dim[0] * dim[0]))
    else:
        if stage == "PMI":
            print("\n* Reading the data from the previous run")
            log.write("\n* Reading the data from the previous run")
            # g_rw = array_loader(stage, main_path)
            g_rw = array_loader("Normalized_random_walk", main_path)

    return (g_rw)


def my_random_walk(p_matrix, dim, iter, log, from_file, stage, PMI_coef, main_path):  # ???n s???
    # c??ng th???c normalization n?? : https://towardsdatascience.com/preprocessing-with-sklearn-a-complete-and-comprehensive-guide-670cb98fcfb9
    if not from_file:
        if iter == "infinite":
            model = "the matrix inverse"
        else:
            model = iter + " iterations"
        print("\n* Random walk on the relations using %s " % (model))
        log.write("\n* Random walk on the relations using %s iteration\n" % (iter))

        alpha = 0.75

        start_time = time.time()
        if iter == "infinite":
            print("    Normalizing the relation matrix ... ")
            # print(np.isfinite(np.asanyarray(p_matrix)).all())
            # kh??ng bi???t l?? c??ch l??m n??y c?? t???o ra 1 b???n sao c???n c???p ph??t v??ng nh??? kh??ng
            # norm = l2
            # norm_l2 = np.sqrt(np.sum((p_matrix**2), axis=1)) # norm_l2 shape (n_rows, )
            # norm_l2 = norm_l2.reshape(-1,1) # (n_rows, ) -> (n_rows, 1)
            # p_matrix /= norm_l2 # apply broadcasting (n_rows, n_cols)-(n_rows, 1) --> l??u ?? l?? n??n d??ng /= s??? inplace tr??n v??ng d??? li???u v?? kh??ng thay ?????i ki???u d??? li???u c???a p_matrix

            # norm = l1
            # norm_l1 = np.sum(abs(p_matrix), axis=1)  # norm_l2 shape (n_rows, ) # h??nh nh?? code nh?? v???y n?? xin ra v??ng nh??? m???i ch???c l?? abs() qu??
            norm_l1 = np.array([np.sum(abs(v)) for v in p_matrix])
            # norm_l1_reshape = norm_l1.reshape(-1, 1)  # (n_rows, ) -> (n_rows, 1)
            # p_matrix[norm_l1>0, :] /= norm_l1_reshape[norm_l1>0,:]  # apply broadcasting (n_rows, n_cols)-(n_rows, 1) kh??ng hi???u sao n?? b??? l???i xin c???p th??m v??ng nh??? ??? ????y ta

            for i in range(len(p_matrix)):
                if norm_l1[i] > 0:
                    p_matrix[i, :] /= norm_l1[i]

            array_writer(p_matrix, "p_matrix", "bin", main_path)

            # to solve the singular matrix problem
            print(
                "    Adding very small random values in the matrix so it is not a singular matrix")  # singular matrix l?? g?? qu??n r ta
            random.seed(7)
            for i in range(dim[0] - 1):
                if np.random.rand() > .5:
                    p_matrix[i, i] += random.uniform(0, 0.00001)
                else:
                    p_matrix[i, i] -= random.uniform(0, 0.00001)

            print("    Random walk begins - matrix inverse calculation might take long")
            # Grw = (I - alpha*P)^-1

            p_matrix *= alpha
            print('hello')
            identity_matrix = np.identity(dim[0], dtype=np.float16)
            print('hello')
            identity_matrix -= p_matrix
            del (p_matrix)
            gc.collect()
            print('hello')
            g_rw = inv_scipy(identity_matrix)  # output tr??? v??? v???n l?? float 32 nha # causes memory problem # h??i v???y -----------------------
            del (identity_matrix)
            gc.collect()
            # g_rw = inv_dense(np.identity(dim[0]) - (alpha * p_matrix))      # causes memory problem

        else:
            print("    Random walk begins - matrix multiplication might take long")
            print("    Normalizing the relation matrix ... ")
            p_matrix = preprocessing.normalize(p_matrix, norm='l1')

            # Grm_r = alpha^r*P^r + Grw_(r_1)
            G_last = np.identity(dim[0], dtype=np.float16)  # initializing G0
            alp_itr = alpha
            p_matrix_itr = p_matrix
            pbar = ProgressBar(widgets=[Percentage(), Bar()], maxval=int(iter))
            for i in pbar(range(int(iter))):
                s = time.time()
                g_rw = alp_itr * p_matrix_itr + G_last
                G_last = g_rw
                alp_itr *= alpha
                p_matrix_itr = np.dot(p_matrix_itr, p_matrix)
                f = time.time()
                print("iteration %d takes %s seconds" % (i + 1, str(round(f - s))))

            del (p_matrix_itr)

        finish_time = time.time()
        print("        Graph of random walk is created")
        log.write("    Graph of random walk was created in %.3f seconds\n" % (finish_time - start_time))
        gc.collect()

        array_writer(g_rw, "random_walk", "bin", main_path)

        # to check the number of non-zero elements after the random walk
        print("    Checking the number of non-zero elements in random walk matrix")
        # non_zero = len(g_rw[np.nonzero(g_rw)])
        non_zero = -10
        print("        %d elements out of %d elements are non-zero after the random walk" % (non_zero, dim[0] * dim[0]))
        log.write(
            "    %d elements out of %d elements are non-zero after the random walk\n" % (non_zero, dim[0] * dim[0]))

    else:
        if stage == "random_walk":
            print("\n* Reading graph of random walk from the previous run")
            log.write("\n* Reading graph of random walk from the previous run")
            g_rw = array_loader(stage, main_path)

    if not from_file or (from_file and stage == "random_walk"):
        # PMI calculation
        # PMI(Mij) = dim[0] x (Mij)/(Sum(elements in column j))
        print("\n* Calculating PMI+")
        log.write("\n* Calculating PMI+\n")

        # max(0,log [G(x|y)/G(x123...n)])
        start_time = time.time()
        col_sum = np.sum(g_rw, axis=0)  # sum of each column
        col_sum[col_sum == 0.0] = random.uniform(0, 0.0000001)

        # g_rw must be multiplied by a number [PMI_coef] otherwise the PMI result will be 0 for all elements
        # PMI_coef is the number of words in the main paper
        PMI_coef = dim[0]

        # an experiment on PMI_coef
        """
        digit = 0
        while PMI_coef > 10:
            PMI_coef /= 10
            digit += 1
        PMI_coef = int(math.pow(10,digit))
        """
        # m???i ?? trong ma tr???n g_rw th?? m??nh c?? th??? h???i l?? x??c xu???t ?????ng xu???t hi???n c???a 2 t??? ???? ?
        g_rw *= PMI_coef  # n???u nh??n cho t???ng h??ng th?? m??nh s??? ra ???????c k?? v???ng s??? l???n ?????ng xu???t hi???n c???a 2 t??? t????ng ???ng ????ng kh??ng ta?
        pbar = ProgressBar(widgets=[Percentage(), Bar()], maxval=dim[0])
        # for i in pbar(range(dim[0])): # m???y c??ch vi???t n??y v?? c??ng d???ng c???a pbar h??nh nh?? gi???ng v???i pdtm l?? ch??? ????? m??nh bi???t ti???n h??nh ???? th???c hi???n ???????c bao nhi??u ph???n tr??m.
        #     denominator = col_sum[i]
        #     for j in range(dim[1]):
        #         element = float(g_rw[i,j])/denominator  # H??nh nh?? c??ng th???c c?? g?? ???? sai sai, sao n??i l?? chia cho sum c???a c???t th??? j m??. C??i n??y th?? x??t m???c ?????nh l?? chia cho sum c???a c???t th??? i r???i.
        #         if element <= 1:                            # N???u mu???n s???a th?? ph???i ?????i th??? t??? v??ng l???p ????ng kh??ng?
        #             g_rw[i, j] = 0
        #         else:
        #             g_rw[i, j] = math.log(element, 2)

        # C???i thi???n t???c ????? t??nh to??n c???a code b???ng numpy v?? vi???t l???i cho ????ng theo c??ng th???c h??? ghi tr??n kia.
        for j in pbar(range(dim[1])):
            denominator = col_sum[j]
            g_rw[:, j] = g_rw[:, j] / denominator
            g_rw[g_rw[:, j] <= 1, j] = 0
            if len(g_rw[:, j] > 1) > 0:
                g_rw[g_rw[:, j] > 1, j] = np.log2(g_rw[g_rw[:, j] > 1, j])

        finish_time = time.time()

        print("    PMI+ is created")
        log.write("    PMI+ was created in %.3f seconds\n" % (finish_time - start_time))

        array_writer(g_rw, "PMI", "bin", main_path)

        print("    Checking the number of non-zero elements in PMI matrix")
        # non_zero = len(g_rw[np.nonzero(g_rw)])
        non_zero = -10
        print("        %d elements out of %d elements are non-zero in PMI matrix" % (non_zero, dim[0] * dim[0]))
        log.write("    %d elements out of %d elements are non-zero in PMI matrix\n" % (non_zero, dim[0] * dim[0]))
    else:
        if stage == "PMI":
            print("\n* Reading the data from the previous run")
            log.write("\n* Reading the data from the previous run")
            # g_rw = array_loader(stage, main_path)
            g_rw = array_loader("Normalized_random_walk", main_path)

    return (g_rw)


def matrix_arc_update(p_matrix, synonym_index, accepted_rel, dim, max_depth, log, from_file, stage, main_path):
    """
    dim = (11,11)
    p_matrix = np.zeros(dim,dtype = np.float16)
    p_matrix[0, 1] = 1
    p_matrix[0, 2] = 1
    p_matrix[0, 3] = 1
    p_matrix[1, 0] = 0
    p_matrix[1, 4] = 1
    p_matrix[1, 5] = 1
    p_matrix[1, 6] = 1
    p_matrix[2, 0] = 1
    p_matrix[2, 6] = 1
    p_matrix[2, 7] = 1
    p_matrix[2, 8] = 1
    p_matrix[3, 0] = 1
    p_matrix[3, 9] = 1
    p_matrix[4, 1] = 1
    p_matrix[4, 10] = 1
    p_matrix[5, 1] = 1
    p_matrix[5, 10] = 1
    p_matrix[6, 1] = 1
    p_matrix[6, 2] = 0
    p_matrix[7, 2] = 1
    p_matrix[7, 10] = 1
    p_matrix[8, 2] = 1
    p_matrix[9, 3] = 1
    p_matrix[10, 4] = 1
    p_matrix[10, 5] = 1
    p_matrix[10, 1] = 1
    """
    print("\n* Random walk on nodes with maximum distance = %d" % (max_depth))

    start_time = time.time()
    if not from_file:
        alpha = 0.75

        trans = {}
        for i in range(dim[0]):
            trans.update({i: np.nonzero(p_matrix[i])[0]})  # original connections
        p_matrix = one_traverse(trans, max_depth, p_matrix, alpha, )  # moving from root to the leaves

        # post_process for synonymy relations
        if "syn" in accepted_rel:
            for itm in synonym_index:
                p_matrix[itm[0], itm[1]] = 1.0

        if "self_loop" in accepted_rel:
            np.fill_diagonal(p_matrix, 1.1)

        print("    Graph of random walk is created")
        print("    Checking the number of non-zero elements in Random walk matrix")
        # non_zero = len(p_matrix[np.nonzero(p_matrix)])
        non_zero = -10

        print("        %d elements out of %d elements are non-zero in Random walk matrix" % (non_zero, dim[0] * dim[0]))
        log.write(
            "    %d elements out of %d elements are non-zero in Random walk matrix\n" % (non_zero, dim[0] * dim[0]))

        finish_time = time.time()
        log.write("    Graph of random walk was created in %.3f seconds\n" % (finish_time - start_time))
        array_writer(p_matrix, "random_walk", "bin", main_path)
    else:
        print("    Reading graph of Random Walk saved in the previous run")
        p_matrix = array_loader(stage, main_path)
    return (p_matrix)


def one_traverse(trans, max_depth, p_matrix, alpha):
    start_p = 0
    end_p = len(p_matrix)

    temp_row_index = -1
    for i in range(start_p, end_p):  # i is the root in the traverse
        node_st = time.time()
        temp_row_index += 1
        closeness_score = 1  # shows the distance from the root
        aux_queue = []  # a queue of to be traverse nodes
        seen_node = set()
        seen_node_cnt = {}

        for target in trans[i]:
            aux_queue.append((1, i, target))  # directly connected nodes to the root. i->target will be traversed
        seen_node.add(i)
        seen_node_cnt[i] = 1

        while closeness_score != max_depth and aux_queue != []:  # left to right breath first traverce with no loops
            (distance, prev, current_node) = aux_queue.pop(0)

            if distance == closeness_score + 1:  # next level
                closeness_score += 1

            next_closeness_score = closeness_score + 1
            if current_node not in seen_node or seen_node_cnt[current_node] < 5:
                for target in trans[current_node]:
                    if target not in seen_node or seen_node_cnt[target] < 5:
                        aux_queue.append((next_closeness_score, current_node, target))

                    if target not in seen_node:
                        seen_node.add(target)
                        seen_node_cnt[target] = 1
                    else:
                        seen_node_cnt[target] += 1

                if current_node not in seen_node:
                    seen_node.add(current_node)
                    seen_node_cnt[current_node] = 1
                else:
                    seen_node_cnt[current_node] += 1

                # seen_node.add(current_node)

            if p_matrix[temp_row_index][current_node] == 0:
                p_matrix[temp_row_index][current_node] = alpha ** closeness_score
            else:
                p_matrix[temp_row_index][current_node] += alpha ** closeness_score

        print("node %d ends, max distance %d, time %s" % (i, closeness_score, str(node_st - time.time())))

    return p_matrix

def dimensionality_reduction_PCA_and_write_to_file(word_list, emb_matrix, vec_dim, from_file, normalization, norm, log, iter, main_path):
    sklearn_limit = 60000
    if emb_matrix != [] and vec_dim > len(emb_matrix[0]):
        print("    no need for dimentionality reduction")
        print(len(emb_matrix[0]))
        if normalization:
            if norm == 0 and from_file:
                print("    Loading the normalized results from the previous run")
                emb_vec = emb_matrix
            else:
                start_time = time.time()
                if norm == 1:
                    p_degree = 'l1'
                elif norm == 2:
                    p_degree = 'l2'
                print("    Normalizing the results using %s norm" % (p_degree))
                emb_vec = preprocessing.normalize(emb_matrix, norm=p_degree)
                finish_time = time.time()
                print("        the results are normalized")
                log.write("    The results were normalized in %.3f seconds using %s norm\n" % (
                    finish_time - start_time, p_degree))
    else:
        emb_vec = []

        if len(emb_matrix) > sklearn_limit:
            print("Sklearn does not work accurately in such high dimensions")

        print("\n*Dimensionality reduction using " +  "Sklearn.PCA" )
        log.write("\n*Dimensionality reduction using " +  "Sklearn.PCA" + "\n")

        # Normalization
        if normalization:
            if norm == 0 and from_file:
                print("    Loading the normalized results from the previous run")
                # emb_matrix = array_loader("Normalized_random_walk", main_path)
            else:
                start_time = time.time()
                if norm == 1:
                    p_degree = 'l1'
                else:
                    p_degree = 'l2'
                print("    Normalizing graph of random walk, using %s norm" % (p_degree))
                norm_l2 = np.sqrt([np.sum(v ** 2) for v in emb_matrix])

                for i in range(len(emb_matrix)):
                    if norm_l2[i] > 0:
                        emb_matrix[i, :] /= norm_l2[i]

                finish_time = time.time()
                print("        Random walk results are normalized")
                log.write("    Random walk results were normalized in %.3f seconds using %s norm\n" % (
                    finish_time - start_time, p_degree))
                array_writer(emb_matrix, "Normalized_random_walk", "bin", main_path)

        # PCA with sklearn
        start_time = time.time()
        # linear PCA
        print("PCA begins")
        pca = PCA_sklearn(copy=True, n_components=vec_dim, whiten=False)
        jump=3000 # ph???i l???n h??n gi?? tr??? c???a vec_dim
        start=0
        out_file = open(main_path + "embeddings_" + iter + ".txt", "w")
        to_keep = len(word_list)
        out_file.write("%d %d\n" % (to_keep, vec_dim))
        try:
            while start + jump <= to_keep:
                print(start)

                matrix_pca = pca.fit_transform(emb_matrix[start:start + jump])
                if vec_dim > len(emb_matrix[0]):
                    vec_dim = len(emb_matrix[0])
                pbar = ProgressBar(widgets=[Percentage(), Bar()], maxval=start + jump)
                for i in pbar(range(start, start + jump)):
                    wrd = word_list[i]
                    emb = ""
                    for j in range(vec_dim):
                        emb += str(matrix_pca[i % jump][j]) + " "
                    emb += "\n"
                    emb = emb.replace(" \n", "\n")  # sao code nh??n t???n chi ph?? qu?? v???y ta v?? d??? code l??: emb[-3:]="\n" ???????c h??n kh??ng.
                    out_file.write(wrd + " " + emb)
                start += jump

            if to_keep % jump != 0:
                matrix_pca = pca.fit_transform(emb_matrix[start:])
                pbar = ProgressBar(widgets=[Percentage(), Bar()], maxval=to_keep)
                for i in pbar(range(start, to_keep)):
                    wrd = word_list[i]
                    emb = ""
                    for j in range(vec_dim):
                        emb += str(matrix_pca[i % jump][j]) + " "
                    emb += "\n"
                    emb = emb.replace(" \n", "\n")  # sao code nh??n t???n chi ph?? qu?? v???y ta v?? d??? code l??: emb[-3:]="\n" ???????c h??n kh??ng.
                    out_file.write(wrd + " " + emb)

            out_file.close()
            print("\n-------------------------------------------------------------")
            print("Vector Embeddings are created and saved in \data\output folder")
            del (emb_matrix)
            gc.collect()
            del (matrix_pca)
            gc.collect()

        except:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            print("Unexpected error:", exc_value)





def dimensionality_reduction(word_list, to_keep, reduction_method, emb_matrix, vec_dim, from_file, normalization, norm,
                             log, saved_model, main_path):
    sklearn_limit = 60000
    if emb_matrix != [] and vec_dim > len(emb_matrix[0]):
        print("    no need for dimentionality reduction")
        print(len(emb_matrix[0]))
        if normalization:
            if norm == 0 and from_file:
                print("    Loading the normalized results from the previous run")
                emb_vec = emb_matrix
            else:
                start_time = time.time()
                if norm == 1:
                    p_degree = 'l1'
                elif norm == 2:
                    p_degree = 'l2'
                print("    Normalizing the results using %s norm" % (p_degree))
                emb_vec = preprocessing.normalize(emb_matrix, norm=p_degree)
                finish_time = time.time()
                print("        the results are normalized")
                log.write("    The results were normalized in %.3f seconds using %s norm\n" % (
                finish_time - start_time, p_degree))
    else:
        emb_vec = []

        if len(emb_matrix) > sklearn_limit:
            print("Sklearn does not work accurately in such high dimensions")

        if "NN-" not in reduction_method:
            approach = "Sklearn." + reduction_method
        else:
            approach = reduction_method

        print("\n*Dimensionality reduction using " + approach)
        log.write("\n*Dimensionality reduction using " + approach + "\n")

        # Normalization
        if normalization:
            if norm == 0 and from_file:
                print("    Loading the normalized results from the previous run")
                # emb_matrix = array_loader("Normalized_random_walk", main_path)
            else:
                start_time = time.time()
                if norm == 1:
                    p_degree = 'l1'
                else:
                    p_degree = 'l2'
                print("    Normalizing graph of random walk, using %s norm" % (p_degree))
                norm_l2 = np.sqrt([np.sum(v ** 2) for v in emb_matrix])

                for i in range(len(emb_matrix)):
                    if norm_l2[i] > 0:
                        emb_matrix[i, :] /= norm_l2[i]

                finish_time = time.time()
                print("        Random walk results are normalized")
                log.write("    Random walk results were normalized in %.3f seconds using %s norm\n" % (
                finish_time - start_time, p_degree))
                array_writer(emb_matrix, "Normalized_random_walk", "bin", main_path)

        # PCA with sklearn
        start_time = time.time()
        if reduction_method == "PCA":
            # linear PCA
            print("PCA begins")
            pca = PCA_sklearn(copy=True, n_components=vec_dim, whiten=False)
            emb_vec = pca.fit_transform(emb_matrix)
        elif reduction_method == "IPCA":
            # increamental PCA
            """
            ipca = inc_PCA_sklearn(n_components=vec_dim, batch_size = 1500 )
            emb_vec = ipca.fit_transform(emb_matrix)
            """
            ipca = inc_PCA_sklearn(n_components=vec_dim)
            batch_size = int(len(emb_matrix) / 5)  # bach_size must be bigger than the final dimention

            # to fit the model
            st = 0
            while st < len(emb_matrix):
                en = st + batch_size
                if en >= len(emb_matrix):
                    en = len(emb_matrix)
                section = emb_matrix[st:en, :]
                print("    fit batch %d to %d " % (st, en))
                ipca.partial_fit(section)
                st = en
                """
                precision = ipca.get_precision()
                cov = ipca.get_covariance()
                acc = assert_array_almost_equal(np.dot(cov, precision),
                                          np.eye(section.shape[1]))
                print(acc)
                """

            # to transfor the data
            emb_vec = np.zeros((len(emb_matrix), vec_dim), dtype=np.float16)
            st = 0
            while st < len(emb_matrix):
                en = st + batch_size
                if en >= len(emb_matrix):
                    en = len(emb_matrix)
                section = emb_matrix[st:en, :]
                print("    transform batch %d to %d " % (st, en))
                emb_vec[st:en, :] = ipca.transform(section)
                st = en

        elif reduction_method == "KPCA":
            # Kernel PCA
            kpca = kernel_PCA_sklearn(n_components=vec_dim, kernel='rbf', gamma=0.01000)
            emb_vec = kpca.fit_transform(emb_matrix)
        elif reduction_method == "ISOMap":
            neighbors_num = int((len(emb_matrix[0]) / vec_dim + vec_dim / 2) / 2)
            print("    Number of considered neighbors: %d" % (neighbors_num))
            iso = isopam_sklearn(n_neighbors=neighbors_num, n_components=vec_dim, eigen_solver='auto', tol=0,
                                 max_iter=None, path_method='auto', neighbors_algorithm='auto', n_jobs=4)
            emb_vec = iso.fit_transform(emb_matrix)
        elif "NN-" in reduction_method:
            mode = reduction_method.split("-")[1]
            if saved_model == False:
                emb_vec = nn_dimensionality_reduction(vec_dim, emb_matrix, mode)
            else:
                emb_vec = nn_dimensionality_reduction_from_savedmodel(mode, vec_dim)
        else:
            print("unknown dimensionality reduction approach")

        finish_time = time.time()
        print("    Dimensionality Reduction is done")
        log.write("    Dimensionality Reduction was done in %.3f seconds\n" % (finish_time - start_time))

        del (emb_matrix)
        gc.collect()

    print("    Vector dimension is reduced to %d" % (vec_dim))
    log.write("    Vector dimension is reduced to %d\n" % (vec_dim))

    array_writer(emb_vec, "embeddings_matrix", "bin", main_path)
    return emb_vec, "pcaFeatures", word_list


def sort_rem(matrix, word_list, synonym_index, to_keep, lang):
    if to_keep >= len(matrix):
        print("    No row/column was eliminated")
        new_word_list = word_list
        new_synonym_index = synonym_index
    else:
        print("    removing some of the rows/columns")
        # tr??? v??? danh s??ch c??c t??? c???n gi??? th??i, th?? d??? m??nh t???i ??u b???ng c??ch ????? t???p test l?? train c???a m??nh v??o ???????c kh??ng ta?
        words_to_keep = gensim_wrd_extractor(lang)  # to keep the words that appear in the test_file

        zero_index = [np.where(x == 0)[0] for x in
                      matrix]  # tr??? v??? m???ng 2 chi???u, v???i m???i d??ng l??c n??y s??? ch??? ch???a v??? tr?? c???a ph???n t??? =0 ??? m???i h??ng
        zero_cnt = [len(x) for x in zero_index]
        indx = np.array(zero_cnt)[
               ::-1].argsort()  # ch??a hi???u ???????c ng??? ?? thu???t to??n ??? ????y l???m, l??c n??y c??i index n??y n?? kh??ng c??n t????ng ???ng v??? tr?? v???i m???ng zero ??ndex

        indx = list(indx)
        to_del = len(matrix) - to_keep
        i = 0
        popped = False
        stop = ""  # ch??a hi???u ng??? c???nh d??ng stop n??y
        while i < to_del:
            indx_val = indx[i]
            if word_list[indx_val] == stop:
                break
            if word_list[indx_val] in words_to_keep:
                indx.append(indx.pop(i))  # l???y ph???n t??? ??? ch??? m???c th??? i v?? th??m v??o cu???i list
                if not popped:
                    popped = True
                    stop = word_list[indx_val]
                i -= 1  # do m??nh v???a pop 1 ph???n t??? ra t???i ????ng index i n??n c???n - 1, r???i ra ngo??i v??ng l???p +1 l??n l???i.
            i += 1
        """
        #----------------------------------------------- if only words in the test files are needed
        i = 0 
        indx = []
        while i <len(word_list):
            if word_list[i] not in words_to_keep:
                indx.append(i)
            i += 1
        to_del = len(indx)
        #-----------------------------------------------
        """
        # n???u ????ng th?? code hay khi thay ?????i tr???c ti???p tr??n v??ng nh??? n??y m?? kh??ng xin v??ng nh??? kh??c, v?? m??nh th???y k??ch th?????c v??ng nh??? l?? r???t l???n ????? c?? th??? xin c???p th??m
        matrix = np.delete(matrix, indx[:to_del], axis=0)
        matrix = np.delete(matrix, indx[:to_del], axis=1)
        # c???p nh???t l???i new word list
        new_word_list = []
        for i in range(len(word_list)):
            if i not in indx[:to_del]:
                new_word_list.append(word_list[i])

        # L???c ra l???i nh???ng c???p synnonym index
        new_synonym_index = set()
        synonym_index = list(synonym_index)
        i = 0
        while i < len(synonym_index):
            itm = synonym_index[i]
            if itm[0] in indx[:to_del] or itm[1] in indx[:to_del]:
                synonym_index.remove(itm)
                i -= 1
            i += 1

        # c???p nh???t l???i ch??? s??? ????ng khi x??a nh???ng t??? d?? th???a r???i ??? m???i c???p t??? trong wordnet
        # l??u ?? indx l?? m???ng l??u c??c ch??? m???c nh??
        indx = sorted(indx[:to_del], reverse=True)
        for i in range(len(synonym_index)):
            itm1 = synonym_index[i][0]
            itm2 = synonym_index[i][1]

            for x in indx:  # code hay ?????y
                if itm1 >= x:
                    itm1 -= 1
                if itm2 >= x:
                    itm2 -= 1
            new_synonym_index.add((itm1, itm2))

    return matrix.astype(np.float32), new_word_list, new_synonym_index


def my_sort_rem(sparse_matrix, word_list, synonym_index, to_keep, lang, dim):
    if to_keep >= dim:
        print("    No row/column was eliminated")
        new_word_list = word_list
        new_synonym_index = synonym_index
        new_sparse_matrix = sparse_matrix
    else:
        print("    removing some of the rows/columns")
        # tr??? v??? danh s??ch c??c t??? c???n gi??? th??i, th?? d??? m??nh t???i ??u b???ng c??ch ????? t???p test l?? train c???a m??nh v??o ???????c kh??ng ta?
        words_to_keep = gensim_wrd_extractor(lang)  # to keep the words that appear in the test_file

        rows = np.array([k[0] for k, v in sparse_matrix.items()])
        cols = np.array([k[1] for k, v in sparse_matrix.items()])

        # N???u m??nh l??u ki??u kia th?? ????y l?? ph???n code c???a m??nh
        zeros_cnt = [dim - len(np.where(rows == i)[0]) for i in range(dim)]  # we will retain the structure
        indx = np.array(zeros_cnt)[::-1].argsort() # trong b??o n??i??nh s??? lo???i b??? nh???ng ph???n t??? th??a th???t nh???t t??? tr??n xu???ng d?????i, m?? n???u code nh?? v???y th?? b??? m???t th??? t??? ??? m???ng g???c r???i

        indx = list(indx)
        to_del = dim - to_keep
        i = 0
        popped = False
        stop = ""
        while i < to_del:
            indx_val = indx[i]
            if word_list[indx_val] == stop:
                break
            if word_list[indx_val] in words_to_keep:
                indx.append(indx.pop(i))  # l???y ph???n t??? ??? ch??? m???c th??? i v?? th??m v??o cu???i list
                if not popped:
                    popped = True
                    stop = word_list[indx_val]
                i -= 1  # do m??nh v???a pop 1 ph???n t??? ra t???i ????ng index i n??n c???n - 1, r???i ra ngo??i v??ng l???p +1 l??n l???i.
            i += 1

        # n???u ????ng th?? code hay khi thay ?????i tr???c ti???p tr??n v??ng nh??? n??y m?? kh??ng xin v??ng nh??? kh??c, v?? m??nh th???y k??ch th?????c v??ng nh??? l?? r???t l???n ????? c?? th??? xin c???p th??m
        # code c???a m??nh ch???y ch???m h??n nhi???u l?? do kh??ng d??ng numpy nh?? ng?????i ta
        # set_indx_del = set(sorted(indx[:to_del], reverse=True)) # chuy???n l???i th??nh set ????? t??ng t???c ????? t??m ki???m, nh??ng ch?? ?? khi l???y set th?? s??? m???y th??? t??? sort n??n kh??ng code nh?? v???y
        set_indx_del = set(indx[:to_del])
        arr_indx_del = np.array(indx[:to_del])
        new_sparse_matrix = {}
        for k, v in sparse_matrix.items():
            if k[0] in set_indx_del or k[1] in set_indx_del:
                continue

            idx_row = k[0]
            idx_col = k[1]
            # c???p nh???t l???i ch??? m???c,
            idx_row -= len(np.where(arr_indx_del <= idx_row)[0])
            idx_col -= len(np.where(arr_indx_del <= idx_col)[0])
            new_sparse_matrix.update({(idx_row, idx_col): v})

        # c???p nh???t l???i new word list
        new_word_list = []
        for i in range(len(word_list)):
            if i not in set_indx_del:
                new_word_list.append(word_list[i])

        # L???c ra l???i nh???ng c???p synnonym index
        new_synonym_index = set()
        synonym_index = list(synonym_index)
        i = 0
        while i < len(synonym_index):
            itm = synonym_index[i]
            if itm[0] in set_indx_del or itm[1] in set_indx_del:
                synonym_index.remove(itm)
                i -= 1
            i += 1

        # c???p nh???t l???i ch??? s??? ????ng khi x??a nh???ng t??? d?? th???a r???i ??? m???i c???p t??? trong wordnet
        # l??u ?? indx l?? m???ng l??u c??c ch??? m???c nh??
        for i in range(len(synonym_index)):
            itm1 = synonym_index[i][0]
            itm2 = synonym_index[i][1]

            itm1 -= len(np.where(arr_indx_del <= itm1)[0])
            itm2 -= len(np.where(arr_indx_del <= itm2)[0])
            new_synonym_index.add((itm1, itm2))

        # l??c n??y trong code c???a m??nh s??? ph???i c???p nh???t l???i rows and cols

    return new_sparse_matrix, new_word_list, new_synonym_index


def gensim_wrd_extractor(lang):
    # words_to_keep = set()
    # if lang == "English":
    #     file_name = ["RG1965.tsv", "wordsim_sim.txt", "wordsim353.tsv", "MTURK-771.csv", "simlex999.txt"]
    #     src_path = os.getcwd() + '/data/input/English_testset/'
    # elif lang == "Portuguese":
    #     file_name = ["LX-SimLex-999.txt", "LX-WordSim-353.txt"]
    #     src_path = os.getcwd() + '/data/input/Portuguese_testset/'
    # else:
    #     file_name = ["RG1965.tsv", "wordsim353.tsv"]
    #     src_path = os.getcwd() + '/data/input/Dutch_testset/'

    # for fn in file_name:
    #     path =  src_path + fn
    #     fl = open(path)
    #     src = fl.readlines()
    #     fl.close()
    #
    #     print("    number of words in " + fn + " is " + str(len(src)))
    #
    #     for line in src:
    #         if "# " in line:
    #             continue
    #         parts = line.split("\t")
    #         words_to_keep.add(parts[0])
    #         words_to_keep.add(parts[1])
    f_in = open('dict.txt', 'r')
    lines = f_in.readlines()
    words_to_keep = [line.strip() for line in lines]

    print("    final number of words to keep " + str(len(words_to_keep)))

    return words_to_keep


def nn_dimensionality_reduction(vec_dim, emb_matrix, mode):
    epochs = 2
    batch_size = 100

    inp = Input(shape=(len(emb_matrix),))
    encoded = Dense(vec_dim, activation='relu', use_bias=True, activity_regularizer=regularizers.l1(10e-5))(
        inp)  # encoded representation of the input
    # encoded = Dense(vec_dim, activation='tanh', use_bias=False, activity_regularizer=regularizers.l1(10e-5))(inp)  # encoded representation of the input
    # encoded = Dense(vec_dim, activation='relu', use_bias=False,)(inp)                              # encoded representation of the input
    decoded = Dense(len(emb_matrix), activation='sigmoid', trainable=True)(encoded)  # lossy reconstruction of the input

    model = Model(inp, decoded)  # maps an input to its reconstruction
    model.compile(optimizer='adadelta', loss='binary_crossentropy', metrics=['acc'])
    model.summary()

    encoder = Model(inp, encoded)  # To access the mid-layers

    if mode == "1Hot":
        model.fit(np.identity(len(emb_matrix)), emb_matrix, batch_size=batch_size, epochs=epochs, verbose=1,
                  callbacks=None,
                  validation_split=0.0, validation_data=None, shuffle=True,
                  class_weight=None, sample_weight=None, initial_epoch=0)
        encoded_inp = encoder.predict(np.identity(len(emb_matrix)))

    elif mode == "encoder":
        model.fit(emb_matrix, emb_matrix, batch_size=batch_size, epochs=epochs, verbose=1, callbacks=None,
                  validation_split=0.0, validation_data=None, shuffle=True,
                  class_weight=None, sample_weight=None, initial_epoch=0)
        encoded_inp = encoder.predict(emb_matrix)

    # To save the model
    model.save(os.getcwd() + '/data/output/model_' + mode)
    print("    The model is saved...")

    # To save layer1 output
    array_writer(encoded_inp, "layer1_output", "bin")

    # To save the weights (no bias)
    print("    Extracting the weights ...")
    weights = []
    biases = []
    for i in range(1, len(model.layers)):  # layer_1(input) weights/biases are 0, so no need to save them
        layer = model.layers[i]
        temp = np.array(layer.get_weights()[0], dtype=np.float16)  # weights
        weights.append(temp)
        if len(layer.get_weights()) > 1:
            temp = np.array(layer.get_weights()[1], dtype=np.float16)  # biases
        else:
            temp = []
        biases.append(temp)

    array_writer(weights, "weights_" + mode, "bin")
    array_writer(biases, "biases_" + mode, "bin")

    return (weights[0])


def nn_dimensionality_reduction_from_savedmodel(mode, vec_dim):
    # weights of last layer
    weights = array_loader("weights_" + mode)
    return (np.transpose(weights[1]))
    # return (weights[0])

    weights = array_loader("weights_" + mode)[0]
    bias = array_loader("biases_" + mode)[0] / len(weights)
    bias_temp = np.tile(bias, (len(weights), 1))
    # emb_vec = weights + bias_temp
    emb_vec = np.transpose(array_loader("weights_" + mode)[1]) + bias_temp
    return (emb_vec)

    # encoded_input * weights of layer1
    # emb_vec = array_loader("layer1_output") * array_loader("weights_" + mode)[0]
    # emb_vec = array_loader("layer1_output") * np.transpose(array_loader("weights_" + mode)[1])
    # emb_vec = array_loader("weights_" + mode)[0] + np.transpose(array_loader("weights_" + mode)[1])
    # return (emb_vec)

    """
    model = load_model(os.getcwd() + "/data/output/model_" + mode)
    # To get layer1 output using functions
    print("    Extracting the mid-layer output ...")
    get_1st_layer_output = K.function([model.layers[0].input], [model.layers[1].output])
    if mode == "1Hot":
        layer1_output = get_1st_layer_output([np.identity(len(emb_matrix))])[0]
    else:
        layer1_output = get_1st_layer_output([emb_matrix])[0]
    array_writer(layer1_output, "layer1_output", "bin")

    layer1_output = array_loader("layer1_output")

    return (layer1_output)
    """
