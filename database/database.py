# 데이터베이스 API
import json
from typing import List

from database.connection import connect


class ResultSet(object):
    def __init__(self, columns: List[str], result_set: List[tuple]):
        self.result_set = {}
        for row in result_set:
            # Database.select 함수에서 모든 열의 첫 번째 요소는 기본 키로 나오도록 함
            primary_key = row[0]
            self.result_set[primary_key] = {}
            for index in range(len(columns)):
                column = columns[index]
                value = row[index]
                self.result_set[primary_key][column] = value
        self.data = result_set
        self.columns = columns

    def __getitem__(self, primary_key: int):
        return self.result_set[primary_key]

    def __str__(self):
        return self.result_set.__str__()

    def __repr__(self):
        return self.result_set.__repr__()

    def values(self):
        return self.result_set.values()

    def keys(self):
        return self.result_set.keys()

    def column(self, column: str):
        return [row[column] for row in self.values()]


class Database:
    primary_key = {
        'exchange': 'exchange_id',
        'chat': 'chat_id',
        'channel': 'channel_id',
        'alarm': 'alarm_id',
        'condition': 'condition_id'
    }

    def __init__(self, database_url: str, debug=False):
        self.conn = connect(database_url)
        self.debug = debug

        self.conn.autocommit = True

    # SQL 쿼리문을 작성할 때 코드의 변수를 조건문의 비교 값으로 사용하기 위해
    #   1) 변수가 문자열이라면 따옴표로 감쌈
    #   2) 변수가 부울형이라면 정수형으로 변환
    @staticmethod
    def to_comparison_value(value):
        if type(value) is str:
            return f'\'{value}\''

        elif type(value) is dict:
            return f"\'{json.dumps(value)}\'"

        elif value is None:
            return 'null'

        else:
            return str(value)

    # 매개변수의 키와 값으로 SQL 쿼리문에 작성할 조건문을 작성
    @staticmethod
    def to_parameter_statement(seperator=", ", *args, **kwargs):
        parameter_list = []

        if args == ():  # 키워드 인수로 비교 값이 전달될 경우
            for key, value in kwargs.items():
                parameter_list.append(f"{key}={Database.to_comparison_value(value)}")

        elif kwargs == {}:  # 위치 인수로 비교 값이 전달될 경우
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
            cursor.close()
            return result_set  # 결과 집합 반환

    # 해당 테이블의 컬럼명 반환
    def get_primary_column(self, table_name: str) -> str:
        primary_column = self.primary_key[table_name]
        return primary_column

    def select(self, table_name: str, columns: list = None, **kwargs) -> ResultSet:
        """
        SELECT문을 실행하고 결과 집합을 반환함
        :param table_name: str, 테이블명
        :param columns: List[str], 지정할 컬럼
        :param kwargs: Dict[str, Any], 지정할 조건 (예: '컬럼명'='값')
        :return: ResultSet, 쿼리문을 실행한 결과 집합
        """
        # 실행할 쿼리문
        query = f"SELECT "
        # 컬럼 지정
        if columns:
            primary_column = self.get_primary_column(table_name)
            # 지정한 컬럼에 기본 키 컬럼이 없을 경우 가장 앞에 기본 키 컬럼을 추가함
            if primary_column not in columns:
                columns.insert(0, primary_column)
            query += ', '.join(columns)
        else:
            query += "*"
        query += f" FROM {table_name} "
        # 조건 지정
        if kwargs != {}:
            parameter_statement = self.to_parameter_statement(seperator=" AND ", **kwargs)
            query += "WHERE " + parameter_statement
        query += ";"
        # 쿼리문을 실행하고 결과 집합을 저장함
        result_set = self.execute(query)
        # 결과 집합 반환
        return result_set

    def insert(self, table_name: str, **kwargs) -> int:
        """
        INSERT문을 실행하고 입력한 열의 ID를 반환함
        :param table_name: str, 테이블명
        :param kwargs: Dict[str, Any], 입력할 컬럼과 그 값
        :return: ResultSet, 쿼리문을 실행한 결과 집합
        """
        # 값을 입력할 컬럼
        columns = tuple(kwargs.keys())
        # 입력할 값
        values = tuple(kwargs.values())
        # 해당 테이블의 기본 키 컬럼명
        primary_column = self.get_primary_column(table_name)
        # 컬럼 지정문
        column_statement = ', '.join(columns)
        # 조건문
        parameter_statement = self.to_parameter_statement(', ', *values)
        # 실행할 쿼리문
        query = f"INSERT INTO {table_name} ({column_statement}) VALUES ({parameter_statement})"
        query += f" RETURNING {primary_column};"
        # 쿼리문을 실행하고 결과 집합을 저장함
        # 해당 결과 집합에는 입력한 열의 기본 키 정보가 담겨 있음
        result_set = self.execute(query)
        # 입력한 열의 기본 키 반환
        return result_set.data[0][0]

    def update(self, table_name: str, primary_key: int, **kwargs):
        """
        UPDATE문을 실행함
        :param table_name: str, 테이블명
        :param primary_key: int, 수정할 열의 기본 키
        :param kwargs: Dict[str, Any], 수정할 컬럼과 그 값
        """
        # 해당 테이블의 기본 키 컬럼명
        primary_column = self.get_primary_column(table_name)
        # 조건문
        parameter_statement = self.to_parameter_statement(**kwargs)
        # 실행할 쿼리문
        query = f"UPDATE {table_name} SET {parameter_statement} WHERE {primary_column}={primary_key};"
        self.execute(query)

    # DELETE문 실행
    def delete(self, table_name: str, **kwargs):
        """
        DELETE문을 실행함
        :param table_name: str, 테이블명
        :param kwargs: Dict[str, Any], 지정할 조건 (예: '컬럼명'='값')
        """
        # 실행할 쿼리문
        query = f"DELETE FROM {table_name}"
        # 조건 지정
        if kwargs != {}:
            parameter_statement = self.to_parameter_statement(seperator=" AND ", **kwargs)
            query += " WHERE " + parameter_statement
        query += ';'
        # 쿼리문 실행
        self.execute(query)

    def is_exists(self, table_name: str, primary_key: int = None, **kwargs) -> bool:
        """
        해당 열이 해당 테이블에 존재하는지 여부를 반환함
        :param table_name: str, 테이블명
        :param primary_key: int, 기본 키
        :param kwargs: Dict[str, Any], 지정할 조건 (예: '컬럼명'='값')
        :return: bool, 해당 열 존재 여부
        """
        # 해당 테이블의 기본 키 컬럼명
        primary_column = self.get_primary_column(table_name)
        # 기본 키가 주어진 경우 해당 기본 키로 검색함
        if primary_key is not None:
            condition_state = f"{primary_column}={self.to_comparison_value(primary_key)}"
        # 기본 키가 주어지지 않은 경우 주어진 조건으로 검색함
        else:
            condition_state = self.to_parameter_statement(**kwargs)
        # 실행할 쿼리문
        query = f"SELECT EXISTS(SELECT {primary_column} FROM {table_name} WHERE {condition_state});"
        # 쿼리문을 실행하고 결과 집합을 저장함
        result_set = self.execute(query)
        # 해당 열의 존재 여부
        existence = bool(result_set.to_list()[0][0])
        return bool(existence)

    def is_exchange_exists(self, exchange_id: int) -> bool:
        return self.is_exists(table_name='exchange', primary_key=exchange_id)

    def is_chat_exists(self, chat_id: int) -> bool:
        return self.is_exists(table_name='chat', primary_key=chat_id)

    def is_channel_exists(self, channel_id: int) -> bool:
        return self.is_exists(table_name='channel', primary_key=channel_id)

    def is_alarm_exists(self, alarm_id: int) -> bool:
        return self.is_exists(table_name='alarm', primary_key=alarm_id)
