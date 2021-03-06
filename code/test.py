import os
os.environ["CUDA_VISIBLE_DEVICES"] = "1"
import pickle 
import numpy as np
import helper_functions
import warnings
with warnings.catch_warnings():
    warnings.filterwarnings('ignore', category=FutureWarning)
    import tensorflow as tf
    import keras

np.random.seed(0)
tf.set_random_seed(0)

NUM_TRAIN = 2**8 + 2**6
MAX_DEFN_LEN = 20
FRAC_VAL = 0.2
NUM_EPOCH = 100
a_LSTM = 128

# Read in word-clue pairs
with open('../data/word_clue_pairs.txt', 'rb') as fp:
    word_clue_pairs_list = pickle.load(fp)

# Read in word-glove pairs
with open('../data/word_glove_pairs_word_all.txt', 'rb') as fp:
    word_glove_pairs_dict = pickle.load(fp)
    word_to_index_dict = pickle.load(fp)
    index_to_word_dict = pickle.load(fp)
glove_length = len(word_glove_pairs_dict['a'])

# Read in word-definition pairs
with open('../data/word_defn_pairs.txt', 'rb') as fp:
    word_defn_pairs_dict = pickle.load(fp)

# Make a new list: for the word-clue pairs whose words appear in the word-glove
#   dict and in the GCIDE dict, translate that pair into a pair [emb_word, 
#   emb_clue_list], where emb_clue_list is the list [emb_clue_word_0, 
#   emb_clue_word_1, ...].
words, indices, clues, definitions, num_pairs_added, max_clue_length, max_defn_length = helper_functions.choose_word_clue_pairs_with_dict(NUM_TRAIN, word_clue_pairs_list, word_glove_pairs_dict, word_to_index_dict, word_defn_pairs_dict)

print('\nNum pairs added: ' + str(num_pairs_added) + '\n')
#for i in range(20):
#    print(words[i], definitions[i])

# Add start, end, and pad tokens to word-glove pairs dict, clip definitions, and append start, end, and pad tokens to each clue and definition
word_glove_pairs_dict, word_to_index_dict, index_to_word_dict, training_clue_indices, definition_indices, clues, definitions = helper_functions.add_tokens_with_dict(word_glove_pairs_dict, word_to_index_dict, index_to_word_dict, glove_length, clues, max_clue_length, np, definitions, MAX_DEFN_LEN)

# Define the training set
x_train_a0 = np.zeros((num_pairs_added, a_LSTM))
x_train_c0 = np.zeros((num_pairs_added, a_LSTM))
# x_train_word_index = np.array(indices)
x_train_definition_indices = np.array(definition_indices) 
x_train_clue_indices = np.array(training_clue_indices)
x_train = [x_train_a0, x_train_c0, x_train_definition_indices, x_train_clue_indices]

#print(max_clue_length, len(word_glove_pairs_dict))

y_train = np.zeros((num_pairs_added, max_clue_length + 2, len(word_glove_pairs_dict)), dtype = 'float16')
for m in range(num_pairs_added):
    clue = clues[m]
    shifted_clue = clue[1:] + ['<PAD>']
    for i in range(max_clue_length + 2):
        y_train[m, i, word_to_index_dict[shifted_clue[i]]] = 1
#y_train = np.transpose(y_train, (1, 0, 2))
#y_train = list(y_train)

# Make the embedding matrix
embedding_matrix = np.zeros((len(word_glove_pairs_dict), glove_length))
for word in word_to_index_dict.keys():
    embedding_matrix[word_to_index_dict[word]] = np.array(word_glove_pairs_dict[word])

# Define the training model
masking_layer = keras.layers.Masking(mask_value = word_to_index_dict['<PAD>'], input_shape = (None,))
embedding_layer = keras.layers.Embedding(len(word_glove_pairs_dict), glove_length, weights = [embedding_matrix], trainable = False, name = 'embedding')
encoder_LSTM = keras.layers.LSTM(a_LSTM, return_state = True, return_sequences = True, name = 'encoder_LSTM', recurrent_dropout = 0.2)
encoder_LSTM_bwd = keras.layers.LSTM(a_LSTM, return_state = True, return_sequences = True, name = 'encoder_LSTM_bwd', go_backwards = True, recurrent_dropout = 0.2)
dense_encoder_output = keras.layers.Dense(a_LSTM, activation = 'tanh')
dense_between_a = keras.layers.Dense(a_LSTM, activation = 'tanh')
dense_between_c = keras.layers.Dense(a_LSTM, activation = 'tanh')
decoder_LSTM = keras.layers.LSTM(a_LSTM, return_state = True, return_sequences = True, name = 'decoder_LSTM', recurrent_dropout = 0.2)
squeezer = keras.layers.Lambda(lambda x: x[:, 0, :])
repeater = keras.layers.RepeatVector(MAX_DEFN_LEN)
attn_dense_1 = keras.layers.Dense(64, activation = "tanh")
attn_dropout = keras.layers.Dropout(0.2)
attn_dense_2 = keras.layers.Dense(1, activation = "relu")
attn_softmax = keras.layers.Softmax(axis = 1)
attn_dot = keras.layers.Dot(axes = 1)
attn_dense_3 = keras.layers.Dense(64)
dropout_layer = keras.layers.Dropout(0.4)
dense_layer = keras.layers.Dense(len(word_glove_pairs_dict))
softmax_activation = keras.layers.Activation('softmax')

a0 = keras.layers.Input(shape = (a_LSTM,), name = 'a0')
c0 = keras.layers.Input(shape = (a_LSTM,), name = 'c0')
defn_indices = keras.layers.Input(shape = (MAX_DEFN_LEN,), dtype = 'int32', name = 'defn_indices')
clue_indices = keras.layers.Input(shape = (None,), dtype = 'int32', name = 'clue_indices')

masked_defn_indices = masking_layer(defn_indices)
x_defn = embedding_layer(masked_defn_indices)
encoder_output, a, c = encoder_LSTM(x_defn, initial_state = [a0, c0])
encoder_bwd_output, a_bwd, c_bwd = encoder_LSTM_bwd(x_defn, initial_state = [a0, c0])
encoder_output_concat = keras.layers.Concatenate()([encoder_output, encoder_bwd_output])
encoder_output_densed = dense_encoder_output(encoder_output_concat)
a_concat = keras.layers.Concatenate()([a, a_bwd])
c_concat = keras.layers.Concatenate()([c, c_bwd])
a_passed = dense_between_a(a_concat)
c_passed = dense_between_c(c_concat)

#print(max_clue_length)

for t in range(max_clue_length + 2):
    clue_index = keras.layers.Lambda(lambda x: keras.backend.expand_dims(x[:, t], axis = -1))(clue_indices) 
    masked_clue_index = masking_layer(clue_index)
    x_clue = embedding_layer(masked_clue_index)
    output_dec, a_passed, c_passed = decoder_LSTM(x_clue, initial_state = [a_passed, c_passed])
    output = squeezer(output_dec)
    output = repeater(output)
    output = keras.layers.Concatenate(axis = -1)([output, encoder_output_densed])
    output = attn_dense_1(output)
    output = attn_dropout(output)
    output = attn_dense_2(output)
    output = attn_softmax(output)
    output = attn_dot([output, encoder_output_densed])
    output = keras.layers.Concatenate()([output, output_dec])
    output = attn_dense_3(output)
    output = dropout_layer(output)
    output = dense_layer(output)
    output = softmax_activation(output)
    if t == 0:
        outputs = output
    else:
        outputs = keras.layers.Concatenate(axis = 1)([outputs, output])

model = keras.models.Model(inputs = [a0, c0, defn_indices, clue_indices], outputs = outputs)

# Compile the training model
model.compile(optimizer = 'adam', loss = 'categorical_crossentropy', metrics = ['categorical_accuracy']) 

# Summarize the training model
print(model.summary())
assert(1==0)
# Visualize training model
#keras.utils.plot_model(model, to_file='model.png', show_shapes = True)

# Fit the training model (train)
hist = model.fit(x_train, y_train, validation_split = FRAC_VAL, epochs = NUM_EPOCH, verbose = 1)
#with open('test_stats_model_with_attn.txt', 'wb') as fp: 
#    pickle.dump(hist.history, fp)

#model.save('test_trained_model_with_attn.h5')
