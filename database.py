# 데이터베이스 API
import os
import json
from typing import Union, List

from connection import connect


class DatabaseFileNotFoundError(Exception):
    def __init__(self):
        super().__init__('Could not find database file.')


class ResultSet(dict):
    def __init__(self, column: list, result_set: List[list]):
        for row in result_set:
            self.__setitem__(row[0], {key: val for key, val in zip(column, row)})

        self.column = column
        self.result_set = result_set
    
    def to_list(self):
        return self.result_set


class Database:
    schema = {
        'exchange': {
            'exchange_id': int,
            'exchange_name': str
        },
        'chat': {
            'chat_id': int
        },
        'channel': {
            'channel_id': int,
            'channel_name': str
        },
        'alarm': {
            'alarm_id': int,
            'channel_id': int,
            'exchange_id': int,
            'base_symbol': str,
            'quote_symbol': str,
            'condition_id': int,
            'is_enabled': bool
        },
        'condition': {
            'condition_id': int,
            'whale': dict,
            'tick': dict,
            'bollinger_band': dict,
            'rsi': dict
        }
    }


    class ExistingDataError(Exception):
        def __init__(self):
            super().__init__('This data already exists.')


    def __init__(self, database_url: str, debug=False):
        self.conn = connect(database_url)
        self.debug = debug

        self.conn.autocommit = True

    
    # SQL 쿼리문을 작성할 때 코드의 변수를 조건문의 비교 값으로 사용하기 위해
    #   1) 변수가 문자열이라면 따옴표로 감쌈
    #   2) 변수가 부울형이라면 정수형으로 변환
    @staticmethod
    def to_comparison_value(value):
        if type(value) == str:
            return f'\'{value}\''

        elif type(value) == dict:
            return f"\'{json.dumps(value)}\'"

        elif value == None:
            return 'null'
        
        else:
            return str(value)

    
    # 매개변수의 키와 값으로 SQL 쿼리문에 작성할 조건문을 작성
    @staticmethod
    def to_parameter_statement(seperator=", ", *args, **kwargs):
        parameter_list = []

        if args == ():    # 키워드 인수로 비교 값이 전달될 경우
            for key, value in kwargs.items():
                parameter_list.append(f"{key}={Database.to_comparison_value(value)}")
        
        elif kwargs == {}:    # 위치 인수로 비교 값이 전달될 경우
            parameter_list = [Database.to_comparison_value(value) for value in args]
            
        return seperator.join(parameter_list)

    
    # 쿼리문을 실행
    def execute(self, query: str) -> ResultSet:
        if self.debug:
            print("================")
            print(f"Query: {query}")

        cursor = self.conn.cursor()
        cursor.execute(query)

        try:
            column = [tu[0] for tu in cursor.description]
            result = cursor.fetchall()

        except TypeError:
            return ResultSet([], [])

        else:
            result_set = ResultSet(column, result)
            if self.debug:
                print(result_set)

            return result_set   # 결과 집합 반환

    
    # 해당 테이블의 컬럼명 반환
    def get_primary_column(self, table_name: str) -> str:
        primary_column = list(self.schema[table_name].keys())[0]

        return primary_column
        
    
    # SELECT문 실행
    def select(self, table_name: str, columns=[], **kwargs) -> ResultSet:
        query = f"SELECT "

        if columns != []:
            query += ', '.join(columns)
        
        else:
            query += "*"

        query += f" FROM {table_name} "
    
        # 조건 지정
        if kwargs != {}:
            query += "WHERE " + self.to_parameter_statement(seperator=" AND ", **kwargs)

        query += ";"

        result_set = self.execute(query)

        return result_set   # 결과 집합 반환

    
    # INSERT문 실행
    def insert(self, table_name: str, **kwargs) -> int:
        columns = tuple(kwargs.keys())
        values = tuple(kwargs.values())

        query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({self.to_parameter_statement(', ', *values)}) RETURNING {table_name}_id;"
        
        result_set = self.execute(query)
        
        return result_set.to_list()[0][0]
    
    
    # UPDATE문 실행
    def update(self, table_name: str, primary_key, **kwargs):
        primary_column = self.get_primary_column(table_name)
        columns = list(kwargs.keys())

        query = f"UPDATE {table_name} SET {self.to_parameter_statement(**kwargs)} WHERE {primary_column}={self.to_comparison_value(primary_key)}"

        self.execute(query)

    
    # DELETE문 실행
    def delete(self, table_name: str, **kwargs):
        query = f"DELETE FROM {table_name}"

        # 조건 지정
        if kwargs != {}:
            print(kwargs)
            query += " WHERE " + self.to_parameter_statement(**kwargs)

        self.execute(query)

    
    # 해당 열이 해당 테이블에 존재하는지 확인
    def is_exists(self, table_name: str, primary_key=None, **kwargs) -> bool:
        if primary_key != None:
            primary_column = self.get_primary_column(table_name)
            condition_state = f"{primary_column}={self.to_comparison_value(primary_key)}"

        else:
            condition_state = self.parameter_statement(**kwargs)
        
        query = f"SELECT EXISTS(SELECT {table_name}_id FROM {table_name} WHERE {condition_state});"
        result_set = self.execute(query)

        return bool(result_set.to_list()[0][0])

    
    def is_exchange_exists(self, exchange_id: int) -> bool:
        return self.is_exists(table_name='exchange', primary_key=exchange_id)

    
    def is_chat_exists(self, chat_id: int) -> bool:
        return self.is_exists(table_name='chat', primary_key=chat_id)


    def is_channel_exists(self, channel_id: int) -> bool:
        return self.is_exists(table_name='channel', primary_key=channel_id)

    
    def is_alarm_exists(self, alarm_id: int) -> bool:
        return self.is_exists(table_name='alarm', primary_key=alarm_id)