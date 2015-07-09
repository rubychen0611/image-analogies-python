import pyflann as pf
import numpy as np
import matplotlib.pyplot as plt
import time
import warnings

from img_preprocess import convert_to_YIQ, convert_to_RGB, compute_gaussian_pyramid, initialize_Bp, remap_luminance
from texture_analogies import compute_features, extract_Bp_feature, best_approximate_match, best_coherence_match, compute_distance
import config as c


if __name__ == '__main__':

    # argv = sys.argv
    #
    # if len(argv) != 5:
    #     print "Usage: python", argv[0], "[imageA] [imageA'] [imageB] [output_file]"
    #     exit()

    # Read image files

    # A_fname  = (argv[1])
    # Ap_fname = (argv[2])
    # B_fname  = (argv[3])
    # Bp_fname = argv[4]
    #
    # A_orig = plt.imread(A_fname)
    # Ap_orig = plt.imread(Ap_fname)
    # B_orig = plt.imread(B_fname)

    # Files for Testing
    A_orig = plt.imread('./images/lf_originals/half_size/fruit-src.jpg')
    Ap_orig = plt.imread('./images/lf_originals/half_size/fruit-filt.jpg')
    B_orig = plt.imread('./images/lf_originals/half_size/boat-src.jpg')
    out_path = './images/lf_originals/output/boat/'

    # A_orig = plt.imread('./images/crosshatch/crosshatch_blurred.jpg')
    # Ap_orig = plt.imread('./images/crosshatch/crosshatch.jpg')
    # B_orig = plt.imread('./images/crosshatch/piano_gradient.jpg')
    # out_path = './images/crosshatch/output/test_3/'

    # A_orig = plt.imread('./../sample-images/analogies/wood_orig_sm.jpg')
    # Ap_orig = plt.imread('./../sample-images/analogies/real_wood_orig_sm.jpg')
    # B_orig = plt.imread('./../sample-images/analogies/wood_relit_sm_2p5_2.jpg')
    # Bp_fname = './../sample-images/analogies/output/real_wood_relit_sm_2p5_2_k25.jpg'

    artistic_filter = True

    assert(A_orig.shape == Ap_orig.shape)
    assert(len(A_orig.shape) == len(B_orig.shape)) # same number of channels

    # This is all the setup code

    begin_time = time.time()
    start_time = time.time()

    # Do conversions

    if c.convert:
        A_yiq  = convert_to_YIQ( A_orig/255.)
        Ap_yiq = convert_to_YIQ(Ap_orig/255.)
        B_yiq  = convert_to_YIQ( B_orig/255.)
        A  =  A_yiq[:, :, 0]
        Ap = Ap_yiq[:, :, 0]
        B  =  B_yiq[:, :, 0]
    else:
        A  =  A_orig/255.
        Ap = Ap_orig/255.
        B  =  B_orig/255.

    c.num_ch, c.padding_sm, c.padding_lg, c.weights = c.setup_vars(A)

    # Remap Luminance

    A, Ap = remap_luminance(A, Ap, B)

    # Create Pyramids

    A_pyr  = compute_gaussian_pyramid( A, c.n_sm)
    Ap_pyr = compute_gaussian_pyramid(Ap, c.n_sm)
    B_pyr  = compute_gaussian_pyramid( B, c.n_sm)

    if len(A_pyr) != len(B_pyr):
        max_levels = min(len(A_pyr), len(B_pyr))
        warnings.warn('Warning: input images are very different sizes! The minimum number of levels will be used.')
    else:
        max_levels = len(B_pyr)

    if not artistic_filter:
        Ap_color_pyr = compute_gaussian_pyramid(Ap_orig, c.n_sm)
        Bp_color_pyr = compute_gaussian_pyramid(np.nan * np.ones(B_orig.shape), c.n_sm)

    # Create Random Initialization of Bp

    Bp_pyr = initialize_Bp(B_pyr, init_rand=True)

    stop_time = time.time()
    print 'Environment Setup: %f' % (stop_time - start_time)

    # Compute Feature Vectors

    start_time = time.time()

    A_feat  = compute_features(A_pyr,  c, full_feat=True)
    Ap_feat = compute_features(Ap_pyr, c, full_feat=False)
    B_feat  = compute_features(B_pyr,  c, full_feat=True)

    stop_time = time.time()
    print 'Feature Extraction: %f' % (stop_time - start_time)

    # Build Structures for ANN

    start_time = time.time()

    flann = [pf.FLANN() for _ in xrange(max_levels)]
    params = [list([]) for _ in xrange(max_levels)]
    As = [list([]) for _ in xrange(max_levels)]
    for level in range(1, max_levels):
        As[level] = np.hstack([A_feat[level], Ap_feat[level]])
        params[level] = flann[level].build_index(As[level],
                                      algorithm='autotuned',
                                      target_precision=0.9);
        #print(params[level])

    stop_time = time.time()
    ann_time_total = stop_time - start_time
    print 'ANN Index Creation: %f' % (ann_time_total)

    # # This is the Algorithm Code

    # now we iterate per pixel in each level
    for level in range(1, max_levels):
        start_time = time.time()
        ann_time_level = 0
        print('Computing level %d of %d' % (level, max_levels - 1))

        imh, imw = Bp_pyr[level].shape[0:2]

        Bp_ix = np.arange(imh*imw).reshape((imh, imw))

        s = np.array([])

        # debugging structures
        p_src    = np.nan * np.ones((imh, imw, 3))
        coh_dist = np.zeros((imh, imw))
        app_dist = np.zeros((imh, imw))

        paths = ['%d_psrc.eps'    % (level),
                 '%d_appdist.eps' % (level),
                 '%d_cohdist.eps' % (level),
                 '%d_output.eps'  % (level)]
        vars = [p_src, app_dist, coh_dist, Bp_pyr[level]]

        for row in range(imh):
            for col in range(imw):
                q = row * imw + col

                BBp_feat = extract_Bp_feature(Bp_pyr, B_feat, q, level, row, col, c)

                assert(BBp_feat.shape[0] == As[level].shape[1])

                # Find Approx Nearest Neighbor

                ann_start_time = time.time()

                p_app = best_approximate_match(flann[level], params[level], BBp_feat, As[level].shape[0])

                ann_stop_time = time.time()
                ann_time_level = ann_time_level + ann_stop_time - ann_start_time

                # is this the first iteration for this level?
                # then skip coherence step

                if len(s) < 1:
                    p = np.random.randint(As[level].shape[0])

                # Find Coherence Match and Compare Distances

                else:
                    p_coh = best_coherence_match(As[level], BBp_feat, s, q, row, col, Bp_ix, c)

                    if p_coh == -1: # blue
                        p = p_app
                        p_src[row, col] = np.array([0, 0, 1])
                    else:
                        d_app = compute_distance(As[level][p_app, :], BBp_feat, c.weights)
                        d_coh = compute_distance(As[level][p_coh, :], BBp_feat, c.weights)

                        app_dist[row, col] = d_app
                        coh_dist[row, col] = d_coh

                        if d_coh <= d_app * (1 + 2**(level - max_levels) * c.k):
                            p = p_coh
                            p_src[row, col] = np.array([1, 1, 0])
                        else:
                            p = p_app
                            p_src[row, col] = np.array([1, 0, 0])

                # Get Pixel Value from Ap
                Ap_imw = Ap_pyr[level].shape[1]
                p_col = p % Ap_imw
                p_row = (p - p_col) // Ap_imw

                p_val = Ap_pyr[level][p_row, p_col]

                # Set Bp and Update s

                Bp_pyr[level][row, col] = p_val

                if not artistic_filter:
                    Bp_color_pyr[level][row, col] = Ap_color_pyr[level][p_row, p_col]

                s = np.append(s, p)

        ann_time_total = ann_time_total + ann_time_level

        # Save debugging structures

        for path, var in zip(paths, vars):
            plt.figure()
            plt.imshow(var, interpolation='nearest', cmap='gray')
            plt.axis('off')
            plt.savefig(out_path + path, bbox_inches='tight', pad_inches=0) #
            plt.close()

        #plt.imsave(Bp_fname[:-4] + '_bw.jpg', Bp_pyr[level], cmap='gray')

        stop_time = time.time()
        print 'Level %d time: %f' % (level, stop_time - start_time)
        print('Level %d ANN time: %f' % (level, ann_time_level))

    # Output Image

    if artistic_filter:
        #im_out = convert_to_RGB(np.dstack([Bp_pyr[-1], B_yiq[:, :, 1:]]))
        #im_out = np.clip(im_out, 0, 1)
        im_out = Bp_pyr[-1]
    else:
        im_out = Bp_color_pyr[-1]

    # if c.convert:
    #     im_out = convert_to_RGB(Bp_color_pyr[-1])
    # else:
    #     im_out = Bp_pyr[-1]

    end_time = time.time()
    print 'Total time: %f' % (end_time - begin_time)
    print('ANN time: %f' % ann_time_total)

    #plt.imshow(im_out)
    #plt.show()

    #plt.imsave(Bp_fname, im_out, cmap='gray')