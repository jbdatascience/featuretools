import pytest

from featuretools.synthesis.deep_feature_synthesis import (
    DeepFeatureSynthesis, check_stacking, match)
from featuretools.primitives import (
    Feature, Count, Mean, Sum, TimeSinceLast, AggregationPrimitive,
    get_aggregation_primitives, make_agg_primitive)
from featuretools.variable_types import (Numeric, Index, Variable,
                                         DatetimeTimeIndex)
from featuretools import calculate_feature_matrix
from ..testing_utils import make_ecommerce_entityset, feature_with_name
from datetime import datetime


@pytest.fixture(scope='module')
def es():
    return make_ecommerce_entityset()


@pytest.fixture
def child_entity(es):
    return es['customers']


@pytest.fixture
def grandchild_entity(es):
    return es['sessions']


@pytest.fixture
def child(es, child_entity):
    return Count(es['sessions']['id'],
                 parent_entity=child_entity)


@pytest.fixture
def parent_class():
    return Mean


@pytest.fixture
def parent_entity(es):
    return es['regions']


@pytest.fixture
def parent(parent_class, parent_entity, child):
    return make_parent_instance(parent_class,
                                parent_entity, child)


@pytest.fixture
def test_primitive():
    class TestAgg(AggregationPrimitive):
        name = "test"
        input_types = [Numeric]
        return_type = Numeric
        stack_on = []

        def get_function(self):
            return None

    return TestAgg


def make_parent_instance(parent_class, parent_entity, base_feature,
                         where=None):
    return parent_class(base_feature, parent_entity, where=where)


def test_get_depth(es):
    log_id_feat = es['log']['id']
    customer_id_feat = es['customers']['id']
    count_logs = Count(log_id_feat,
                       parent_entity=es['sessions'])
    sum_count_logs = Sum(count_logs,
                         parent_entity=es['customers'])
    num_logs_greater_than_5 = sum_count_logs > 5
    count_customers = Count(customer_id_feat,
                            parent_entity=es['regions'],
                            where=num_logs_greater_than_5)
    num_customers_region = Feature(count_customers, es["customers"])

    depth = num_customers_region.get_depth()
    assert depth == 5


def test_makes_count(es):
    dfs = DeepFeatureSynthesis(target_entity_id='sessions',
                               entityset=es,
                               filters=[],
                               agg_primitives=[Count],
                               trans_primitives=[])

    features = dfs.build_features()
    assert feature_with_name(features, 'device_type')
    assert feature_with_name(features, 'customer_id')
    assert feature_with_name(features, 'customers.region_id')
    assert feature_with_name(features, 'customers.age')
    assert feature_with_name(features, 'COUNT(log)')
    assert feature_with_name(features, 'customers.COUNT(sessions)')
    assert feature_with_name(features, 'customers.regions.language')
    assert feature_with_name(features, 'customers.COUNT(log)')


def test_count_null_and_make_agg_primitive(es):
    def count_func(values, count_null=False):
        if len(values) == 0:
            return 0

        if count_null:
            values = values.fillna(0)

        return values.count()

    def count_get_name(self):
        where_str = self._where_str()
        use_prev_str = self._use_prev_str()
        return u"COUNT(%s%s%s)" % (self.child_entity.name,
                                   where_str,
                                   use_prev_str)

    Count = make_agg_primitive(count_func, [[Index], [Variable]], Numeric,
                               name="count", stack_on_self=False,
                               cls_attributes={"_get_name": count_get_name})
    count_null = Count(es['log']['value'], es['sessions'], count_null=True)
    feature_matrix = calculate_feature_matrix([count_null], entityset=es)
    values = [5, 4, 1, 2, 3, 2]
    assert (values == feature_matrix[count_null.get_name()]).all()


def test_check_input_types(es, child, parent):
    mean = parent
    assert mean._check_input_types()
    boolean = child > 3
    mean = make_parent_instance(Mean, es['regions'],
                                child, where=boolean)
    assert mean._check_input_types()


def test_base_of_and_stack_on_heuristic(es, test_primitive, child):
    test_primitive.stack_on = []
    child.base_of = []
    assert not (check_stacking(test_primitive, [child]))

    test_primitive.stack_on = []
    child.base_of = None
    assert (check_stacking(test_primitive, [child]))

    test_primitive.stack_on = []
    child.base_of = [test_primitive]
    assert (check_stacking(test_primitive, [child]))

    test_primitive.stack_on = None
    child.base_of = []
    assert (check_stacking(test_primitive, [child]))

    test_primitive.stack_on = None
    child.base_of = None
    assert (check_stacking(test_primitive, [child]))

    test_primitive.stack_on = None
    child.base_of = [test_primitive]
    assert (check_stacking(test_primitive, [child]))

    test_primitive.stack_on = [child]
    child.base_of = []
    assert (check_stacking(test_primitive, [child]))

    test_primitive.stack_on = [child]
    child.base_of = None
    assert (check_stacking(test_primitive, [child]))

    test_primitive.stack_on = [child]
    child.base_of = [test_primitive]
    assert (check_stacking(test_primitive, [child]))


def test_stack_on_self(es, test_primitive, parent_entity):
    # test stacks on self
    child = test_primitive(es['log']['value'], parent_entity)
    test_primitive.stack_on = []
    child.base_of = []
    test_primitive.stack_on_self = False
    child.stack_on_self = False
    assert not (check_stacking(test_primitive, [child]))

    test_primitive.stack_on_self = True
    assert (check_stacking(test_primitive, [child]))

    test_primitive.stack_on = None
    test_primitive.stack_on_self = False
    assert not (check_stacking(test_primitive, [child]))


# P TODO: this functionality is currently missing
# def test_max_depth_heuristic(es, parent_class, parent_entity, parent):
#     grandparent = make_parent_instance(parent_class, parent_entity,
#                                        parent)
#     for f in [parent, grandparent]:
#         f.stack_on = ['child']
#         f.stack_on_self = True
#         f.base_of = ['parent']
#         f.apply_to = [(Numeric,)]
#         f.max_stack_depth = 2

#     assert parent.can_apply(parent_entity, 'customers')
#     assert not grandparent.can_apply(parent_entity, 'customers')

#     grandparent.max_stack_depth = 3
#     assert grandparent.can_apply(parent_entity, 'customers')

def test_init_and_name(es):
    session = es['sessions']
    log = es['log']

    features = [Feature(v) for v in log.variables]
    for agg_prim in get_aggregation_primitives():

        input_types = agg_prim.input_types
        if type(input_types[0]) != list:
            input_types = [input_types]

        # test each allowed input_types for this primitive
        for it in input_types:
            # use the input_types matching function from DFS
            matching_types = match(it, features)
            if len(matching_types) == 0:
                raise Exception("Agg Primitive %s not tested" % agg_prim.name)
            for t in matching_types:
                instance = agg_prim(*t, parent_entity=session)

                # try to get name and calculate
                instance.get_name()
                instance.head()


def test_time_since_last(es):
    f = TimeSinceLast(es["log"]["datetime"], es["customers"])
    fm = calculate_feature_matrix([f],
                                  instance_ids=[0, 1, 2],
                                  cutoff_time=datetime(2015, 6, 8))

    correct = [131376600, 131289600, 131287800]
    # note: must round to nearest second
    assert all(fm[f.get_name()].round().values == correct)


def test_time_since_last_custom(es):
    def time_since_last(values, time=None):
        time_since = time - values.iloc[0]
        return time_since.total_seconds()

    TimeSinceLast = make_agg_primitive(time_since_last,
                                       [DatetimeTimeIndex],
                                       Numeric,
                                       name="time_since_last",
                                       uses_calc_time=True)
    f = TimeSinceLast(es["log"]["datetime"], es["customers"])
    fm = calculate_feature_matrix([f],
                                  instance_ids=[0, 1, 2],
                                  cutoff_time=datetime(2015, 6, 8))

    correct = [131376600, 131289600, 131287800]
    # note: must round to nearest second
    assert all(fm[f.get_name()].round().values == correct)

    with pytest.raises(ValueError):
        TimeSinceLast = make_agg_primitive(time_since_last,
                                           [DatetimeTimeIndex],
                                           Numeric,
                                           uses_calc_time=False)


def test_custom_primitive_time_as_arg(es):
    def time_since_last(values, time):
        time_since = time - values.iloc[0]
        return time_since.total_seconds()

    TimeSinceLast = make_agg_primitive(time_since_last,
                                       [DatetimeTimeIndex],
                                       Numeric,
                                       uses_calc_time=True)
    assert TimeSinceLast.name == "time_since_last"
    f = TimeSinceLast(es["log"]["datetime"], es["customers"])
    fm = calculate_feature_matrix([f],
                                  instance_ids=[0, 1, 2],
                                  cutoff_time=datetime(2015, 6, 8))

    correct = [131376600, 131289600, 131287800]
    # note: must round to nearest second
    assert all(fm[f.get_name()].round().values == correct)

    with pytest.raises(ValueError):
        make_agg_primitive(time_since_last,
                           [DatetimeTimeIndex],
                           Numeric,
                           uses_calc_time=False)
