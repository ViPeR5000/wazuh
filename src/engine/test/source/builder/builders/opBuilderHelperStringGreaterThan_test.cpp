
#include <any>
#include <gtest/gtest.h>
#include <vector>

#include <baseTypes.hpp>
#include <defs/failDef.hpp>

#include "opBuilderHelperFilter.hpp"

using namespace base;
namespace bld = builder::internals::builders;

TEST(opBuilderHelperStringGreaterThan, Builds)
{
    auto tuple = std::make_tuple(std::string {"/field"},
                                 std::string {"string_greater"},
                                 std::vector<std::string> {"value1"},
                                 std::make_shared<defs::mocks::FailDef>());

    ASSERT_NO_THROW(std::apply(bld::opBuilderHelperStringGreaterThan, tuple));
}

TEST(opBuilderHelperStringGreaterThan, Exec_greater_than_false)
{
    auto tuple = std::make_tuple(std::string {"/field2check"},
                                 std::string {"string_greater"},
                                 std::vector<std::string> {"value2"},
                                 std::make_shared<defs::mocks::FailDef>());

    auto event1 = std::make_shared<json::Json>(R"({"field2check": "value1"})");

    auto op = std::apply(bld::opBuilderHelperStringGreaterThan, tuple)->getPtr<Term<EngineOp>>()->getFn();

    result::Result<Event> result = op(event1);

    ASSERT_FALSE(result.success());
}

TEST(opBuilderHelperStringGreaterThan, Exec_greater_than_true)
{
    auto tuple = std::make_tuple(std::string {"/field2check"},
                                 std::string {"string_greater"},
                                 std::vector<std::string> {"value1"},
                                 std::make_shared<defs::mocks::FailDef>());

    auto event1 = std::make_shared<json::Json>(R"({"field2check": "value2"})");

    auto op = std::apply(bld::opBuilderHelperStringGreaterThan, tuple)->getPtr<Term<EngineOp>>()->getFn();

    result::Result<Event> result = op(event1);

    ASSERT_TRUE(result.success());
}

TEST(opBuilderHelperStringGreaterThan, Exec_greater_than_ref_false)
{
    auto tuple = std::make_tuple(std::string {"/field2check"},
                                 std::string {"string_greater"},
                                 std::vector<std::string> {"$otherfield"},
                                 std::make_shared<defs::mocks::FailDef>());

    auto event1 = std::make_shared<json::Json>(R"({"field2check": "value1",
                                                   "otherfield": "value2"})");

    auto op = std::apply(bld::opBuilderHelperStringGreaterThan, tuple)->getPtr<Term<EngineOp>>()->getFn();

    result::Result<Event> result = op(event1);

    ASSERT_FALSE(result.success());
}

TEST(opBuilderHelperStringGreaterThan, Exec_greater_than_ref_true)
{
    auto tuple = std::make_tuple(std::string {"/field2check"},
                                 std::string {"string_greater"},
                                 std::vector<std::string> {"$otherfield"},
                                 std::make_shared<defs::mocks::FailDef>());

    auto event1 = std::make_shared<json::Json>(R"({"field2check": "value2",
                                                   "otherfield": "value1"})");

    auto op = std::apply(bld::opBuilderHelperStringGreaterThan, tuple)->getPtr<Term<EngineOp>>()->getFn();

    result::Result<Event> result = op(event1);

    ASSERT_TRUE(result.success());
}

TEST(opBuilderHelperStringGreaterThan, Exec_greater_than_multilevel_false)
{
    auto tuple = std::make_tuple(std::string {"/parentObjt_1/field2check"},
                                 std::string {"string_greater"},
                                 std::vector<std::string> {"value2"},
                                 std::make_shared<defs::mocks::FailDef>());

    auto event1 = std::make_shared<json::Json>(R"({
                    "parentObjt_2": {
                        "field2check": 10,
                        "ref_key": 10
                    },
                    "parentObjt_1": {
                        "field2check": "value1",
                        "ref_key": 11
                    }
                    })");

    auto op = std::apply(bld::opBuilderHelperStringGreaterThan, tuple)->getPtr<Term<EngineOp>>()->getFn();

    result::Result<Event> result = op(event1);

    ASSERT_FALSE(result.success());
}

TEST(opBuilderHelperStringGreaterThan, Exec_greater_than_multilevel_true)
{
    auto tuple = std::make_tuple(std::string {"/parentObjt_1/field2check"},
                                 std::string {"string_greater"},
                                 std::vector<std::string> {"value1"},
                                 std::make_shared<defs::mocks::FailDef>());

    auto event1 = std::make_shared<json::Json>(R"({
                    "parentObjt_2": {
                        "field2check": 10,
                        "ref_key": 10
                    },
                    "parentObjt_1": {
                        "field2check": "value2",
                        "ref_key": 11
                    }
                    })");

    auto op = std::apply(bld::opBuilderHelperStringGreaterThan, tuple)->getPtr<Term<EngineOp>>()->getFn();

    result::Result<Event> result = op(event1);

    ASSERT_TRUE(result.success());
}

TEST(opBuilderHelperStringGreaterThan, Exec_greater_than_multilevel_ref_false)
{
    auto tuple = std::make_tuple(std::string {"/parentObjt_1/field2check"},
                                 std::string {"string_greater"},
                                 std::vector<std::string> {"$parentObjt_2.field2check"},
                                 std::make_shared<defs::mocks::FailDef>());

    auto event1 = std::make_shared<json::Json>(R"({
                    "parentObjt_2": {
                        "field2check": "value2",
                        "ref_key": 10
                    },
                    "parentObjt_1": {
                        "field2check": "value1",
                        "ref_key": 11
                    }
                    })");

    auto op = std::apply(bld::opBuilderHelperStringGreaterThan, tuple)->getPtr<Term<EngineOp>>()->getFn();

    result::Result<Event> result = op(event1);

    ASSERT_FALSE(result.success());
}

TEST(opBuilderHelperStringGreaterThan, Exec_greater_than_multilevel_ref_true)
{
    auto tuple = std::make_tuple(std::string {"/parentObjt_1/field2check"},
                                 std::string {"string_greater"},
                                 std::vector<std::string> {"$parentObjt_2.field2check"},
                                 std::make_shared<defs::mocks::FailDef>());

    auto event1 = std::make_shared<json::Json>(R"({
                    "parentObjt_2": {
                        "field2check": "value1",
                        "ref_key": 10
                    },
                    "parentObjt_1": {
                        "field2check": "value2",
                        "ref_key": 10
                    }
                    })");

    auto op = std::apply(bld::opBuilderHelperStringGreaterThan, tuple)->getPtr<Term<EngineOp>>()->getFn();

    result::Result<Event> result = op(event1);

    ASSERT_TRUE(result.success());
}
