import datetime
import json
from multiprocessing.util import is_exiting
from os import name
import uuid
from requests import delete
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser, JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.contrib.auth import get_user_model
from django.db.models import  Q
from django.db import transaction
from api import models
from api import serializers
from django.db import IntegrityError, DatabaseError
from acl.utils import user_util
from api.utils.file_type import identify_file_type 
from api.utils import shared_fxns
from django.db.models import Sum
import math
from collections import defaultdict


class FoundationViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = models.RRIGoals.objects.all().order_by('id')
    serializer_class = serializers.FetchRRIGoalsSerializer
    search_fields = ['id', ]

    def get_queryset(self):
        return []

    @action(detail=False, methods=["GET"], url_path="completion-analytics")
    def completion_analytics(self, request):
        try:
            goals = models.RRIGoals.objects.filter(is_deleted=False)
            serializer = serializers.ProjectCompletionAnalyticsSerializer(goals, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            # print("Error in completion_analytics:", e)
            return Response({"error": "Unable to fetch completion analytics"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)    
    
    @action(detail=False, methods=["GET"], url_path="progress-by-sector")
    def progress_by_sector(self, request):
        try:
            sectors = defaultdict(list)
            goals = models.RRIGoals.objects.filter(is_deleted=False)

            for goal in goals:
                sector_name = goal.wave.directorate.sub_sector.sector.name if goal.wave.directorate.sub_sector.sector else "Unspecified"
                # completion_data = goal.completion_analytics or {}
                # print(sector_name)
                completion_data = serializers.ProjectCompletionAnalyticsSerializer(goal) or {}
                completion = completion_data.get_completion(goal)
                sectors[sector_name].append(completion)

            data = []
            for name, completions in sectors.items():
                avg = sum(completions) / len(completions) if completions else 0
                data.append({
                    "sector": name,
                    "completion": math.ceil(avg)
                })

                # print(data)
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            print("Error in progress_by_sector:", e)
            return Response({"error": "Unable to compute sector progress"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
   
    @action(detail=False, methods=["GET"], url_path="project-progress-by-sub-sector")
    def sub_sector_project_progress(self, request):
        """Retrieves the individual progress of a project within a particular sub-sector."""
        sub_sector = request.query_params.get("subsector")
        try:
            sub_sector_data = list()
            goals = models.RRIGoals.objects.filter(is_deleted=False, wave__directorate__sub_sector__name=sub_sector)

            for goal in goals:
                # Extract sub-sector name safely
                sub_sector_name = sub_sector

                # Use serializer to get completion (assuming get_completion is defined in serializer)
                completion_data = serializers.ProjectCompletionAnalyticsSerializer(goal) or {}
                completion = completion_data.get_completion(goal)

                # Add individual project record (goal) under its sub-sector
                sub_sector_data.append({
                    "wave_name": goal.wave.name if goal.wave else "Unnamed Wave",
                    "completion": math.ceil(completion)
                })

            # Convert defaultdict to list of sub-sector groups
            # data = []
            # for sub_sector_name, goals_list in sub_sector_data.items():
            #     data.append({
            #         "sub_sector": sub_sector_name,
            #         "projects": goals_list
            #     })

            return Response(sub_sector_data, status=status.HTTP_200_OK)

        except Exception as e:
            print("Error in progress_by_sub_sector:", e)
            return Response({"error": "Unable to compute sub-sector progress"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=["GET"], url_path="progress-by-sub-sector")
    def progress_by_sub_sector(self, request):
        """Calculates the average progress across all sub-sectors of a given sector"""
        sector = request.query_params.get("sector")
        try:
            sub_sector_data = defaultdict(list)
            # goals = models.RRIGoals.objects.filter(is_deleted=False, wave__directorate__sub_sector__sector__name=sector)
            sub_sectors = models.SubSector.objects.filter(sector__name=sector)
            # print(sub)
            for sub_sector in sub_sectors:
                # Extract sub-sector name safely
                sub_sector_name = sub_sector.name
                temp = models.RRIGoals.objects.filter(is_deleted=False, wave__directorate__sub_sector__name=sub_sector)
                for goal in temp:
                    completion_data = serializers.ProjectCompletionAnalyticsSerializer(goal) or {}
                    completion = completion_data.get_completion(goal)
                    sub_sector_data[sub_sector_name].append(completion)

            # Convert defaultdict to list of sub-sector groups
            data = []
            for sub_sector_name, completions in sub_sector_data.items():
                print(sub_sector_name, completions)
                avg_completion = sum(completions)/len(completions) if completions else 0
                data.append({
                    "sub_sector": sub_sector_name,
                    "completion": math.ceil(avg_completion)
                })

            return Response(data, status=status.HTTP_200_OK)

        except Exception as e:
            print("Error in progress_by_sub_sector:", e)
            return Response({"error": "Unable to compute sub-sector progress"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
   
    @action(methods=["GET"], 
    detail=False,
    url_path="sector-budget-distribution", 
    url_name="sector-budget-distribution")
    def budget_distribution(self, request):
        # get all sectors
        sectors = models.Sector.objects.all()

        # loop through the sector and finding all projects related to each and their budget
        budget_dis = defaultdict(list)
        for sector in sectors:
            sector_projects = models.Wave.objects.filter(directorate__sub_sector__sector__name=sector.name)
            for sector_project in sector_projects:
                if budget_dis[sector.name]:
                    budget_dis[sector.name].append(sector_project.budget)
                else:
                    budget_dis[sector.name].append(sector_project.budget)
        data = []
        for sector, v in budget_dis.items():
            # budget_dis[k] = sum(v)
            data.append({
                "sector": sector,
                "budget": sum(v)
            })
        
        return Response(data, status=status.HTTP_200_OK)

    @action(methods=["POST", "GET", "PUT", "DELETE"],
            detail=False,
            url_path="sector",
            url_name="sector")
    def sector(self, request):
        if request.method == "POST":
            payload = request.data
            serializer = serializers.GeneralNameSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                with transaction.atomic():
                    raw = {
                        "name":name
                    }
                    models.Sector.objects.create(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "PUT":
            payload = request.data
            serializer = serializers.UpdateDepartmentSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                request_id = payload['request_id']

                try:
                    sector = models.Sector.objects.get(Q(id=request_id))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Sector!"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    sector.name = name
                    sector.save()

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            if request_id:
                try:
                    sector = models.Sector.objects.get(Q(id=request_id))
                    sector = serializers.FetchSectorSerializer(sector,many=False).data
                    return Response(sector, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Sector!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    sectors = models.Sector.objects.filter(Q(is_deleted=False)).order_by('name')
                    sectors = serializers.FetchSectorSerializer(sectors,many=True).data
                    return Response(sectors, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
        
        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request !"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                try:
                    raw = {"is_deleted" : True}
                    models.Sector.objects.filter(Q(id=request_id)).update(**raw)
                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)
                        
    @action(methods=["POST", "GET", "PUT", "DELETE"],
            detail=False,
            url_path="sub-sector",
            url_name="sub-sector")
    def sub_sector(self, request):
        if request.method == "POST":
            payload = request.data
            serializer = serializers.CreateSubSectorSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                names = list(set(payload['name']))
                sector = payload['sector']

                try:
                    sector = models.Sector.objects.get(Q(id=sector))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Sector!"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    for name in names:
                        raw = {
                            "name":name,
                            "sector":sector
                        }
                        models.SubSector.objects.create(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "PUT":
            payload = request.data
            serializer = serializers.UpdateSubSectorSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                sector = payload['sector']
                request_id = payload['request_id']

                try:
                    sub_sector = models.SubSector.objects.get(Q(id=request_id))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Sub Sector!"}, status=status.HTTP_400_BAD_REQUEST)
            
                try:
                    sector = models.Sector.objects.get(Q(id=sector))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Sector!"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    sub_sector.name = name
                    sub_sector.sector = sector
                    sub_sector.save()

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            if request_id:
                try:
                    sub_sector = models.SubSector.objects.get(Q(id=request_id))
                    sub_sector = serializers.FetchSubSectorSerializer(sub_sector,many=False).data
                    return Response(sub_sector, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Sub Sector!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    sub_sectors = models.SubSector.objects.filter(Q(is_deleted=False)).order_by('name')
                    sub_sectors = serializers.FetchSubSectorSerializer(sub_sectors,many=True).data
                    return Response(sub_sectors, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)

        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request !"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                try:
                    raw = {"is_deleted" : True}
                    models.SubSector.objects.filter(Q(id=request_id)).update(**raw)
                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=["POST", "GET", "PUT", "DELETE"],
            detail=False,
            url_path="directorate",
            url_name="directorate")
    def directorates(self, request):
        if request.method == "POST":
            payload = request.data
            serializer = serializers.CreateDirectorateSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                names = list(set(payload['name']))
                sub_sector = payload['sub_sector']

                try:
                    sub_sector = models.SubSector.objects.get(Q(id=sub_sector))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Sub Sector!"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    for name in names:
                        raw = {
                            "name": name,
                            "sub_sector": sub_sector
                        }
                        models.Directorate.objects.create(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "PUT":
            payload = request.data
            serializer = serializers.UpdateDirectorateSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                sub_sector = payload['sub_sector']
                request_id = payload['request_id']

                try:
                    directorate = models.Directorate.objects.get(Q(id=request_id))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Directorate!"}, status=status.HTTP_400_BAD_REQUEST)
            
                try:
                    sub_sector = models.SubSector.objects.get(Q(id=sub_sector))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Sub Sector!"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    directorate.name = name
                    directorate.sub_sector = sub_sector
                    directorate.save()

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            if request_id:
                try:
                    directorate = models.Directorate.objects.get(Q(id=request_id))
                    directorate = serializers.FetchDirectorateSerializer(directorate,many=False).data
                    return Response(sub_sector, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Sub Sector!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    directorates = models.Directorate.objects.filter(Q(is_deleted=False)).order_by('name')
                    directorates = serializers.FetchDirectorateSerializer(directorates,many=True).data
                    return Response(directorates, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)

        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request !"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                try:
                    raw = {"is_deleted" : True}
                    models.Directorate.objects.filter(Q(id=request_id)).update(**raw)
                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=["POST", "GET",  "PUT", "DELETE"],
            detail=False,
            url_path="title",
            url_name="title")
    def title(self, request):
        if request.method == "POST":
            payload = request.data
            serializer = serializers.GeneralNameSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                with transaction.atomic():
                    raw = {
                        "name": name
                    }
                    models.Title.objects.create(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "PUT":
            payload = request.data
            serializer = serializers.UpdateDepartmentSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                request_id = payload['request_id']

                try:
                    title = models.Title.objects.get(Q(id=request_id))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown title!"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    title.name = name
                    title.save()

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            if request_id:
                try:
                    title = models.Title.objects.get(Q(id=request_id))
                    title = serializers.FetchTitleSerializer(title,many=False).data
                    return Response(title, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown title!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    titles = models.Title.objects.filter(Q(is_deleted=False)).order_by('name')
                    titles = serializers.FetchTitleSerializer(titles,many=True).data
                    return Response(titles, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
        
        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request !"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                try:
                    raw = {"is_deleted" : True}
                    models.Title.objects.filter(Q(id=request_id)).update(**raw)
                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)        


    @action(methods=["POST", "GET",  "PUT", "DELETE"],
            detail=False,
            url_path="objective-comments",
            url_name="objective-comments")
    def objective_comments(self, request):
        if request.method == "POST":
            payload = request.data
            serializer = serializers.CreateObjectiveCommentSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                type = payload['type'].upper()
                comment = payload['comment']
                goal_id = payload['goal']

                try:
                    goal = models.RRIGoals.objects.get(Q(id=goal_id))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown objective !"}, status=status.HTTP_400_BAD_REQUEST)

                is_existing = models.ObjectiveComment.objects.filter(Q(goal=goal) & Q(type=type)).first()
                with transaction.atomic():
                    raw = {
                        "type": type,
                        "goal": goal,
                        "comment": comment,
                    }

                    if is_existing:
                        is_existing.comment = comment
                        is_existing.save()
                    else:
                        models.ObjectiveComment.objects.create(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "PUT":
            pass
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            goal_id = request.query_params.get('goal_id')
            if request_id:
                try:
                    objective = models.ObjectiveComment.objects.get(Q(id=request_id))
                    objective = serializers.FetchObjectiveCommentSerializer(objective,many=False).data
                    return Response(objective, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown objective!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            elif goal_id:
                try:
                    objective = models.ObjectiveComment.objects.filter(Q(goal=request_id))
                    objective = serializers.FetchObjectiveCommentSerializer(objective,many=True).data
                    return Response(objective, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown objective!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    objectives = models.ObjectiveComment.objects.filter(Q(is_deleted=False)).order_by('type')
                    objectives = serializers.FetchObjectiveCommentSerializer(objectives,many=True).data
                    return Response(objectives, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
        
        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request !"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                try:
                    raw = {"is_deleted" : True}
                    models.ObjectiveComment.objects.filter(Q(id=request_id)).update(**raw)
                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)    
                


    @action(methods=["POST", "GET", "DELETE"],
            detail=False,
            url_path="overseer",
            url_name="overseer")
    def overseer(self, request):
        if request.method == "POST":
            payload = request.data
            serializer = serializers.CreateOverseerSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                contact = str(payload['contact'])
                title = payload['title']

                if not contact:
                    contact = "N/A"

                try:
                    check_contact = int(contact)

                    if len(contact) > 10 or len(contact) < 9:
                        return Response({"details": "Incorect contact format, use: 0700000000"}, status=status.HTTP_400_BAD_REQUEST)
                    
                    elif len(contact) == 10:
                        if contact[0] == '0':
                            contact = contact[1:]
                            contact = "+254" + contact
                        else:
                            return Response({"details": "Incorect contact format, use: 0700000000"}, status=status.HTTP_400_BAD_REQUEST)
                    else:
                        contact = "+254" + contact
                except Exception as e:
                    contact = "N/A"
                    pass

                # user_exists = models.Overseer.objects.filter(Q(contact=contact)).exists()
                # if user_exists:
                #     return Response({"details": "User Already Added!"}, status=status.HTTP_400_BAD_REQUEST)

                name = name.split()
                name = [x.capitalize() for x in name]
                name = " ".join(name)


                try:
                    title = models.Title.objects.get(Q(id=title))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown title!"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    raw = {
                        "name": name,
                        "contact": contact,
                        "title": title,
                    }
                    models.Overseer.objects.create(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            name = request.query_params.get('name')
            if request_id:
                try:
                    overseer = models.Overseer.objects.get(Q(id=request_id))
                    overseer = serializers.FetchOverseerSerializer(overseer,many=False).data
                    return Response(overseer, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Overseer!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            elif name:
                try:
                    overseer = models.Overseer.objects.filter(Q(name=name)).order_by('name')
                    overseer = serializers.FetchOverseerSerializer(overseer,many=True).data
                    return Response(overseer, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    overseer = models.Overseer.objects.filter(Q(is_deleted=False)).order_by('name')
                    overseer = serializers.FetchOverseerSerializer(overseer,many=True).data
                    return Response(overseer, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)

        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request !"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                try:
                    raw = {"is_deleted" : True}
                    models.Overseer.objects.filter(Q(id=request_id)).update(**raw)
                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=["POST", "GET", "PUT", "DELETE"],
            detail=False,
            url_path="thematic-areas",
            url_name="thematic-areas")
    def thematic_areas(self, request):
        if request.method == "POST":
            payload = request.data
            serializer = serializers.CreateThematicAreaSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                area = payload['area']
                sector = payload['sector']
                project = payload['project']
                department = payload['department']       


                try:
                    department = models.Directorate.objects.get(Q(id=department))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown directorate!"}, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    project = models.Wave.objects.get(Q(id=project))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown project!"}, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    sector = models.Sector.objects.get(Q(id=sector))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown sector!"}, status=status.HTTP_400_BAD_REQUEST)
                
                
                with transaction.atomic():
                    raw = {
                        "area": area,
                        "directorate": department,
                        "sector": sector,
                        "project": project,
                    }
                    models.ThematicArea.objects.create(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "PUT":
            payload = request.data
            serializer = serializers.UpdateThematicAreaSerializer(  
                data=payload, many=False)
            if serializer.is_valid():
                request_id = payload['request_id']
                area = payload['area']
                sector = payload['sector']
                project = payload['project']
                department = payload['department']
                

                try:
                    models.ThematicArea.objects.get(Q(id=request_id))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown thematic area!"}, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    project = models.Wave.objects.get(Q(id=project))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown project!"}, status=status.HTTP_400_BAD_REQUEST)

                try:
                    department = models.Directorate.objects.get(Q(id=department))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown directorate !"}, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    sector = models.Sector.objects.get(Q(id=sector))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown sector!"}, status=status.HTTP_400_BAD_REQUEST)
                
                
                with transaction.atomic():
                    raw = {
                        "area": area,
                        "directorate": department,
                        "sector": sector,
                        "project": project,
                    }
                    models.ThematicArea.objects.filter(Q(id=request_id)).update(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            overseer_id = request.query_params.get('overseer_id')
            project_id = request.query_params.get('project_id')
            if request_id:
                try:
                    area = models.ThematicArea.objects.get(Q(id=request_id))
                    area = serializers.FetchThematicAreaSerializer(area,many=False).data
                    return Response(area, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Request!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            if project_id:
                try:
                    area = models.ThematicArea.objects.filter(Q(project=project_id))
                    area = serializers.FetchThematicAreaSerializer(area,many=True).data
                    return Response(area, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Request!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            elif overseer_id:
                try:
                    overseer = models.ThematicArea.objects.filter((Q(results_leader=overseer_id) | Q(team_leader=overseer_id) | Q(team_leader=overseer_id)) & Q(is_deleted=False)).order_by('date_created')
                    overseer = serializers.FetchThematicAreaSerializer(overseer,many=True).data
                    return Response(overseer, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    area = models.ThematicArea.objects.filter(Q(is_deleted=False)).order_by('date_created')
                    area = serializers.FetchThematicAreaSerializer(area,many=True).data
                    return Response(area, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                
        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request !"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                raw = {"is_deleted" : True}
                models.ThematicArea.objects.filter(Q(id=request_id)).update(**raw)
                return Response('200', status=status.HTTP_200_OK)
            


    @action(methods=["POST", "GET", "PUT", "DELETE"],
            detail=False,
            url_path="rri-goals",
            url_name="rri-goals")
    def rri_goals(self, request):
        if request.method == "POST":
            payload = request.data
            serializer = serializers.CreateRRIGoalsSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                wave = payload['wave']
                goal = payload['goal']
                thematic_area = payload['thematic_area']
                results_leaders = payload['results_leaders']
                technical_leaders = payload['technical_leaders']
                strategic_leaders = payload['strategic_leaders']

                if not results_leaders:
                    return Response({"details": "Results Leaders required!"}, status=status.HTTP_400_BAD_REQUEST)
                
                if not technical_leaders:
                    return Response({"details": "Technical Leaders required!"}, status=status.HTTP_400_BAD_REQUEST)
                
                if not strategic_leaders:
                    return Response({"details": "Strategic Leaders required!"}, status=status.HTTP_400_BAD_REQUEST)

                try:
                    thematic_area = models.ThematicArea.objects.get(Q(id=thematic_area))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown thematic area!"}, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    wave = models.Wave.objects.get(Q(id=wave))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown wave!"}, status=status.HTTP_400_BAD_REQUEST)
                                
                
                with transaction.atomic():
                    raw = {
                        "wave": wave,
                        "goal": goal,
                        "results_leaders": results_leaders,
                        "technical_leaders": technical_leaders,
                        "strategic_leaders": strategic_leaders,
                        "thematic_area": thematic_area,
                        "creator": request.user,
                    }
                    rri = models.RRIGoals.objects.create(**raw)

                    team_members = payload['team_members']
                    if team_members:
                        if isinstance(team_members, list):
                            for member in team_members:
                                raw = {
                                    "name": member,
                                    "goal": rri
                                }
                                models.TeamMembers.objects.create(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "PUT":
            payload = request.data
            serializer = serializers.UpdateRRIGoalsSerializer(
                data=payload, many=False)
            
            if serializer.is_valid():
                wave = payload['wave']
                goal = payload['goal']
                thematic_area = payload['thematic_area']
                request_id = payload['request_id']
                results_leaders = payload['results_leaders']
                technical_leaders = payload['technical_leaders']
                strategic_leaders = payload['strategic_leaders']

                if not results_leaders:
                    return Response({"details": "Results Leaders required!"}, status=status.HTTP_400_BAD_REQUEST)
                
                if not technical_leaders:
                    return Response({"details": "Technical Leaders required!"}, status=status.HTTP_400_BAD_REQUEST)
                
                if not strategic_leaders:
                    return Response({"details": "Strategic Leaders required!"}, status=status.HTTP_400_BAD_REQUEST)

                try:
                    rri = models.RRIGoals.objects.get(Q(id=request_id))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown request!"}, status=status.HTTP_400_BAD_REQUEST)

                try:
                    thematic_area = models.ThematicArea.objects.get(Q(id=thematic_area))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown thematic area!"}, status=status.HTTP_400_BAD_REQUEST)
                
                
                try:
                    wave = models.Wave.objects.get(Q(id=wave))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown wave!"}, status=status.HTTP_400_BAD_REQUEST)
                       
                
                with transaction.atomic():
                    raw = {
                        "wave": wave,
                        "goal": goal,
                        "results_leaders": results_leaders,
                        "technical_leaders": technical_leaders,
                        "strategic_leaders": strategic_leaders,
                        "thematic_area": thematic_area,
                        "creator": request.user,
                    }
                    models.RRIGoals.objects.filter(Q(id=request_id)).update(**raw)

                    # update team members
                    team_members = payload['team_members']
                    if team_members:
                        # delete existing members
                        models.TeamMembers.objects.filter(Q(goal=request_id)).delete()
                        # save new members
                        if isinstance(team_members, list):
                            for member in team_members:
                                raw = {
                                    "name": member,
                                    "goal": rri
                                }
                                models.TeamMembers.objects.create(**raw)


                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            thematic_area = request.query_params.get('thematic_area')
            page = request.query_params.get('page')
            selector = request.query_params.get('selector')
            serializer = request.query_params.get('serializer')

            roles = user_util.fetchusergroups(request.user.id)  

            if request_id:
                try:
                    rri = models.RRIGoals.objects.get(Q(id=request_id))
                    rri = serializers.FetchRRIGoalsSerializer(rri,many=False).data
                    return Response(rri, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Request!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            elif thematic_area:
                try:
                    area = models.RRIGoals.objects.filter(Q(thematic_area=thematic_area)).order_by('date_created')
                    area = serializers.FetchRRIGoalsSerializer(area,many=True).data
                    return Response(area, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            elif serializer == 'slim':
                try:
                    area = models.RRIGoals.objects.filter(Q(is_deleted=False)).order_by('goal')
                    area = serializers.SlimFetchRRIGoalsSerializer(area,many=True).data
                    return Response(area, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            elif selector:
                selector_value = request.query_params.get('selector_value')
                location_value = request.query_params.get('location_value')
                location = request.query_params.get('location')

                if not selector_value or not location:
                    return Response({"details": "Select search criteria !"}, status=status.HTTP_400_BAD_REQUEST)
                if location != 'all' and not location_value:
                    return Response({"details": "Select location search criteria !"}, status=status.HTTP_400_BAD_REQUEST)

                if selector == "project":
                    q_filters = Q(wave__id=selector_value)
                elif selector == "objective":
                    q_filters = Q(id=selector_value)
                
                q_filters &= Q(is_deleted=False)

                if location == "borough":
                    q_filters &= Q(wave__location__ward__sub_county__borough__id=location_value)
                elif location == "sub-county":
                    q_filters &= Q(wave__location__ward__sub_county__id=location_value)
                elif location == "ward":
                    q_filters &= Q(wave__location__ward__id=location_value)

                try:
                    area = models.RRIGoals.objects.filter(q_filters).order_by('date_created')
                    area = serializers.FetchRRIGoalsSerializer(area,many=True).data
                    return Response(area, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    if 'EVALUATOR' in roles and page == 'evaluation':
                        assigned = models.AssignedEvaluations.objects.filter(is_evaluated=False,evaluator=request.user).order_by('date_created')
                        ids = assigned.values_list('rri_goal__id', flat=True)
                        area = models.RRIGoals.objects.filter(pk__in=ids).order_by('date_created')
                        area = serializers.FetchRRIGoalsSerializer(area, many=True, context={"user_id":request.user.id}).data
                    else:
                        area = models.RRIGoals.objects.filter(Q(is_deleted=False)).order_by('date_created')
                        area = serializers.FetchRRIGoalsSerializer(area, many=True).data

                    return Response(area, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)

        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request !"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                try:
                    raw = {"is_deleted" : True}
                    models.RRIGoals.objects.filter(Q(id=request_id)).update(**raw)
                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)


    @action(methods=["POST", "GET", "DELETE"],
            detail=False,
            url_path="team-members",
            url_name="team-members")
    def team_members(self, request):
        if request.method == "POST":
            payload = request.data
            serializer = serializers.CreateTeamMembersSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['member']
                thematic_area = payload['thematic_area']

                try:
                    thematic_area = models.ThematicArea.objects.get(Q(id=thematic_area))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown thematic area!"}, status=status.HTTP_400_BAD_REQUEST)
                
                name = name.split()
                name = [x.capitalize() for x in name]
                name = " ".join(name)
                                
                
                with transaction.atomic():
                    raw = {
                        "name": name,
                        "thematic_area": thematic_area
                    }
                    models.TeamMembers.objects.create(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            thematic_area = request.query_params.get('thematic_area')
            if request_id:
                try:
                    members = models.TeamMembers.objects.get(Q(id=request_id))
                    members = serializers.FetchTeamMembersSerializer(members,many=False).data
                    return Response(members, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Request!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            elif thematic_area:
                try:
                    members = models.TeamMembers.objects.filter(Q(thematic_area=thematic_area) & Q(is_deleted=False)).order_by('name')
                    members = serializers.FetchTeamMembersSerializer(members,many=True).data
                    return Response(members, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    members = models.TeamMembers.objects.filter(Q(is_deleted=False)).order_by('name')
                    members = serializers.FetchTeamMembersSerializer(members,many=True).data
                    return Response(members, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
        
        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request !"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                try:
                    raw = {"is_deleted" : True}
                    models.TeamMembers.objects.filter(Q(id=request_id)).update(**raw)
                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)     
                   
                
    @action(methods=["POST"], detail=False, url_path="achievements",url_name="achievements")
    def achievements(self, request):
        authenticated_user = request.user
        formfiles = request.FILES

        payload = json.loads(request.data['payload'])
        serializer = serializers.CreateEvidenceSerializer(
                data=payload, many=False)
        if serializer.is_valid():
            description = payload['description']
            thematic_area = payload['thematic_area_id']
            category = payload['upload_status']

            try:
                thematic_area = models.ThematicArea.objects.get(Q(id=thematic_area))
            except (ValidationError, ObjectDoesNotExist):
                return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            
            if formfiles:
                exts = ['jpeg','jpg','png','tiff','pdf']
                for f in request.FILES.getlist('documents'):
                    original_file_name = f.name
                    ext = original_file_name.split('.')[1].strip().lower()
                    if ext not in exts:
                        return Response({"details": "Only Images and PDFs allowed for upload!"}, status=status.HTTP_400_BAD_REQUEST)
            
            with transaction.atomic():
                achievement = models.Achievement.objects.create(
                    creator=authenticated_user, description=description, thematic_area=thematic_area, category=category)

                if formfiles:                        
                    for f in request.FILES.getlist('documents'):
                        file_type = shared_fxns.identify_file_type(original_file_name.split('.')[1].strip().lower())
                        try:
                            original_file_name = f.name                            
                            models.AchievementDocuments.objects.create(
                                        document=f, original_file_name=original_file_name, 
                                        achievement=achievement, file_type=file_type)

                        except Exception as e:
                            # logger.error(e)
                            print(e)
                            return Response({"details": "Invalid File(s)"}, status=status.HTTP_400_BAD_REQUEST)  
                                            

            user_util.log_account_activity(
                authenticated_user, authenticated_user, "Evidence created", "Evidence Creation Executed")
            return Response('success', status=status.HTTP_200_OK)
        
        else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        

    
    @action(methods=["POST", "GET",  "PUT", "DELETE"],
            detail=False,
            url_path="waves",
            url_name="waves")
    def waves(self, request):
        if request.method == "POST":
            payload = request.data

            print("Payload:", payload) 
            
            serializer = serializers.CreateWaveSerializer(
                data=payload, many=False)
            
            if serializer.is_valid():
                name = payload['name']
                start_date = payload['start_date']
                end_date = payload['end_date']
                financial_year= payload['financial_year']
                # cabinet_memo = payload['cabinet_memo']
                cabinet_memo = payload.get('cabinet_memo')  # Change this line
                print("Cabinet Memo ID:", cabinet_memo)  # Log the ID
                budget = payload['budget']
                directorate = payload['directorate']
                location = payload['location']
                sub_category = payload['sub_category']
                type = payload['type']
                main_project = payload['main_project']
                risks = payload['risks']
                results_leaders = payload['results_leaders']
                technical_leaders = payload['technical_leaders']
                strategic_leaders = payload['strategic_leaders']
                standalone = payload.get('standalone')

                # New fields
                no_cabinet_memo = payload.get('no_cabinet_memo', False)
                no_cabinet_memo_reason = payload.get('no_cabinet_memo_reason', None)
                tender_number = payload['tender_number']

                print(f"Cabinet Memo: {cabinet_memo}, No Cabinet Memo: {no_cabinet_memo}")


                if not no_cabinet_memo:  # This means cabinet memo is required
                   print("Cabinet memo is required. Cabinet Memo:", cabinet_memo)
                   if not cabinet_memo:
                       return Response({"details": "Cabinet memo is required!"}, status=status.HTTP_400_BAD_REQUEST)
                   try:
                       cabinet_memo = models.CabinetMemo.objects.get(id=cabinet_memo)
                   except models.CabinetMemo.DoesNotExist:
                        return Response({"details": "Unknown cabinet memo!"}, status=status.HTTP_400_BAD_REQUEST)
                else:
                    print("No cabinet memo is required.")

 
                
                mother_id = None
                
                ward = location.get('ward')
                
                if ward and ward != "N/A":
                    
                    try:
                        ward = location['ward']
                        ward = models.Ward.objects.get(id=ward)
                        ward = serializers.FetchWardSerializer(ward,many=False).data
                        location['ward'] = ward
                    except Exception as e:
                        print(e)
                        return Response({"details": f"Ward is required!"}, status=status.HTTP_400_BAD_REQUEST) 

                if ward == "SUB":

                    if not main_project:
                        return Response({"details": f"Main Project is required!"}, status=status.HTTP_400_BAD_REQUEST) 
                    
                    try:
                        wave = models.Wave.objects.get(Q(id=main_project))
                    except (ValidationError, ObjectDoesNotExist):
                        return Response({"details": "Unknown main project!"}, status=status.HTTP_400_BAD_REQUEST)
                    
                    mother_id = main_project
                
                if type == "MAIN":
                    if not standalone:
                        return Response({"details": "Standalone status is required"}, status=status.HTTP_400_BAD_REQUEST)

                # added
                try:
                    financial_year= models.BudgetFinancialYear.objects.get(Q(id=financial_year))
                except Exception as e:
                    print(e)
                    return Response({"details": f"Unknown financial year !"}, status=status.HTTP_400_BAD_REQUEST) 
                
                # try:
                #     cabinet_memo= models.CabinetMemo.objects.get(Q(id=cabinet_memo))
                # except Exception as e:
                #     print(e)
                #     return Response({"details": f"Unknown cabinet memo !"}, status=status.HTTP_400_BAD_REQUEST)
                
                 # Only validate cabinet memo if no_cabinet_memo is False
               
                
                
                # end
                
                try:
                    directorate = models.Directorate.objects.get(id=directorate)
                except Exception as e:
                    print(e)
                    return Response({"details": f"Unknown directorate !"}, status=status.HTTP_400_BAD_REQUEST) 
                
                try:
                    sub_category = models.ProjectSubCategory.objects.get(id=sub_category)
                except Exception as e:
                    print(e)
                    return Response({"details": f"Unknown sub category !"}, status=status.HTTP_400_BAD_REQUEST) 

                # check existence of same wave name
                if models.Wave.objects.filter(name__icontains=name).exists():
                    return Response({"details": f"{name} already exists!"}, status=status.HTTP_400_BAD_REQUEST) 

                # validate lead coach
                # try:
                #     lead_coach = get_user_model().objects.get(Q(id=lead_coach))
                # except Exception as e:
                #     print(e)
                #     return Response({"details": "Unknown Lead Coach"}, status=status.HTTP_400_BAD_REQUEST) 
                    

                # find difference in dates / validate dates
                days = shared_fxns.find_date_difference(start_date,end_date,'days')
                            
                try:
                    days = int(days)
                except Exception as e:
                    return Response({"details": f"Invalid dates!"}, status=status.HTTP_400_BAD_REQUEST) 
                
                # if days < 100 or days < 0:
                #     return Response({"details": f"Period is less than 100 days!"}, status=status.HTTP_400_BAD_REQUEST) 

                with transaction.atomic():
                    raw = {
                        "name": name,
                        "start_date": start_date,
                        "end_date": end_date,
                        "financial_year": financial_year,
                        # "cabinet_memo": cabinet_memo,
                        "cabinet_memo": cabinet_memo if not no_cabinet_memo else None,  # Assign None if no_cabinet_memo is True
                        "budget": budget,
                        "directorate": directorate,
                        "sub_category": sub_category,
                        "location": location,
                        "type": type,
                        "mother_id": mother_id,
                        "risks": risks,
                        "results_leaders": results_leaders,
                        "technical_leaders": technical_leaders,
                        "strategic_leaders": strategic_leaders,
                        "standalone": standalone,
                        "no_cabinet_memo": no_cabinet_memo,  # Add the new field
                        "no_cabinet_memo_reason": no_cabinet_memo_reason,
                        "tender_number": tender_number,
                    }
                    models.Wave.objects.create(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "PUT":
            payload = request.data
            serializer = serializers.UpdateWaveSerializer(data=payload, many=False)
            
            if serializer.is_valid():
                name = payload['name']
                start_date = payload['start_date']
                end_date = payload['end_date']
                financial_year= payload['financial_year']
                # cabinet_memo = payload['cabinet_memo']
                cabinet_memo = payload.get('cabinet_memo',None )  # Change this line
                print("Cabinet Memo ID:", cabinet_memo)  # Log the ID
                budget = payload['budget']
                directorate = payload['directorate']
                location = payload['location']
                sub_category = payload['sub_category']
                type = payload['type']
                main_project = payload['main_project']
                risks = payload['risks']
                results_leaders = payload['results_leaders']
                technical_leaders = payload['technical_leaders']
                strategic_leaders = payload['strategic_leaders']
                # standalone = payload.get('standalone')

                # New fields
                no_cabinet_memo = payload.get('no_cabinet_memo', False)
                no_cabinet_memo_reason = payload.get('no_cabinet_memo_reason', None)
                tender_number = payload['tender_number']
                # project_status = payload.get('project_status')

                print(f"Cabinet Memo: {cabinet_memo}, No Cabinet Memo: {no_cabinet_memo}")
                print(tender_number)


                if not no_cabinet_memo:  # If cabinet memo is required
                  if not cabinet_memo:
                    return Response({"details": "Cabinet memo is required!"}, status=status.HTTP_400_BAD_REQUEST)
                 # Additional check for cabinet_memo existence
                  try:
                     cabinet_memo = models.CabinetMemo.objects.get(id=cabinet_memo)
                  except models.CabinetMemo.DoesNotExist:
                    return Response({"details": "Unknown cabinet memo!"}, status=status.HTTP_400_BAD_REQUEST)


                
                mother_id = None
                
                ward = location.get('ward')
                
                if ward and ward != "N/A":
                    
                    try:
                        ward = location['ward']
                        ward = models.Ward.objects.get(id=ward)
                        ward = serializers.FetchWardSerializer(ward,many=False).data
                        location['ward'] = ward
                    except Exception as e:
                        print(e)
                        return Response({"details": f"Ward is required!"}, status=status.HTTP_400_BAD_REQUEST) 


                if type == "SUB":
                
                    if not main_project:
                        return Response({"details": f"Main Project is required!"}, status=status.HTTP_400_BAD_REQUEST) 
                    
                    try:
                        wave = models.Wave.objects.get(Q(id=main_project))
                    except (ValidationError, ObjectDoesNotExist):
                        return Response({"details": "Unknown main project!"}, status=status.HTTP_400_BAD_REQUEST)
                    
                    mother_id = main_project

                if type == "MAIN":
                    if not standalone:
                        return Response({"details": "Standalone status is required"}, status=status.HTTP_400_BAD_REQUEST)

                        
                try:
                    directorate = models.Directorate.objects.get(id=directorate)
                except Exception as e:
                    print(e)
                    return Response({"details": f"Unknown directorate !"}, status=status.HTTP_400_BAD_REQUEST) 

                try:
                    sub_category = models.ProjectSubCategory.objects.get(id=sub_category)
                except Exception as e:
                    print(e)
                    return Response({"details": f"Unknown sub category !"}, status=status.HTTP_400_BAD_REQUEST) 
                
                # Extract request_id from payload or URL
                request_id = payload.get('request_id')  # Or kwargs.get('request_id') if coming from URL

               # Ensure request_id is present
                if not request_id:
                  return Response({"details": "Request ID is required!"}, status=status.HTTP_400_BAD_REQUEST)


               
                
                # validate lead coach
                # try:
                #     lead_coach = get_user_model().objects.get(Q(id=lead_coach))
                # except Exception as e:
                #     print(e)
                #     return Response({"details": "Unknown Lead Coach"}, status=status.HTTP_400_BAD_REQUEST) 
                
                with transaction.atomic():
                    # wave.name = name
                    # wave.start_date = start_date
                    # wave.end_date = end_date
                    # wave.lead_coach = lead_coach
                    # wave.budget = budget
                    # wave.location = location
                    # wave.directorate = directorate
                    # wave.sub_category = sub_category
                    # wave.type = type
                    # wave.mother_id = mother_id
                    
                    # wave.save()
                    raw = {
                        "name": name,
                        "start_date": start_date,
                        "end_date": end_date,
                        "budget": budget,
                        "directorate": directorate,
                        "sub_category": sub_category,
                        "financial_year":financial_year,
                        # "cabinet_memo": cabinet_memo,
                        "cabinet_memo": cabinet_memo if not no_cabinet_memo else None,
                        "location": location,
                        "type": type,
                        "mother_id": mother_id,
                        "risks": risks,
                        "results_leaders": results_leaders,
                        "technical_leaders": technical_leaders,
                        "strategic_leaders": strategic_leaders,
                        "standalone": standalone,
                        "no_cabinet_memo": no_cabinet_memo,  # Update the new field
                        "no_cabinet_memo_reason": no_cabinet_memo_reason,  # Update the new field
                        "tender_number": tender_number,
                        # "project_status": project_status,
                    }
                    models.Wave.objects.filter(Q(id=request_id)).update(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            serializer = request.query_params.get('serializer')
            project_type = request.query_params.get('project_type')
            standalone = request.query_params.get('standalone')
            
            
            if request_id:
                try:
                    # wave = models.Wave.objects.get(Q(id=request_id))
                    wave = models.Wave.objects.select_related('cabinet_memo').get(Q(id=request_id))
                    wave = serializers.FetchWaveSerializer(wave,many=False).data
                    return Response(wave, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown wave!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            elif serializer == 'slim':
                try:
                    waves = models.Wave.objects.filter().order_by('name')
                    waves = serializers.SlimFetchWaveSerializer(waves,many=True).data
                    return Response(waves, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            elif project_type:
                try:
                    if standalone:
                        waves = models.Wave.objects.filter(Q(type=project_type) & Q(standalone=standalone) & Q(is_deleted=False)).order_by('type')
                    else:
                        waves = models.Wave.objects.filter(Q(type=project_type) & Q(is_deleted=False)).order_by('type')
                    waves = serializers.SlimFetchWaveSerializer(waves,many=True).data
                    return Response(waves, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    waves = models.Wave.objects.filter(Q(is_deleted=False)).order_by('name')
                    waves = serializers.FetchWaveSerializer(waves,many=True).data
                    return Response(waves, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
        
        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request !"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                try:
                    raw = {"is_deleted" : True}
                    models.Wave.objects.filter(Q(id=request_id)).update(**raw)
                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)
    
    @action(methods=["POST"],detail=False, url_path="update-project-status", url_name="update-project.status")
    def update_project_status(self, request):
        if request.method == "POST":
            request_id = request.data["id"]
            project_status = request.data["projectStatus"]
            with transaction.atomic():
                try:
                    raw = {"project_status": project_status}
                    models.Wave.objects.filter(Q(id=request_id)).update(**raw)
                    return Response("status updated", status=status.HTTP_200_OK)
                except Exception as e:
                    return Response({"details": e}, status=status.HTTP_400_BAD_REQUEST)
                                      
    @action(methods=["POST"], detail=False, url_path="sub-county-summary", url_name="sub-county-summary")
    def get_sub_county_summary(self, request):
        if request.method == 'POST':
            sub_county = request.data.get("subCounty")  # Correct way to access POST data
            if sub_county:
                get_sub_county = models.Wave.objects.filter(location__ward__sub_county__name=sub_county)
                total_budget = []
                for x in get_sub_county:
                    total_budget.append(x.budget)
                total_budget = sum(total_budget)
                # info = serializers.FetchSubCountyProjectsSerializer(get_sub_county, many=True).data
                return Response({"Number of Projects": len(get_sub_county), "Total budget": total_budget}, status=status.HTTP_200_OK)
            else:
                return Response({"details": "Sub county parameter is missing in the request body"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({"details": "Only POST requests are allowed for this endpoint"}, status=status.HTTP_405_METHOD_NOT_ALLOWED)
    
    @action(methods=["GET"], detail=False, url_path="borough-info", url_name="borough-info")
    def get_borough_info(self, request):
       
        borough = request.query_params.get("borough")  # Correct way to access POST data
        if borough:
            get_borough_projects = models.Wave.objects.filter(location__ward__sub_county__borough__name=borough)            
            info = serializers.FetchBoroughProjectsSerializer(get_borough_projects, many=True).data
            return Response(info, status=status.HTTP_200_OK)
        else:
            return Response({"details": "Borough parameter is missing in the request body"}, status=status.HTTP_400_BAD_REQUEST)  
    
    @action(methods=["GET"], detail=False, url_path="sector-info", url_name="sector-info")
    def get_sector_info(self, request):       
        sector = request.query_params.get("sector")  # Correct way to access POST data
        if sector:
            get_sector_projects = models.Wave.objects.filter(directorate__sub_sector__sector__name=sector)            
            info = serializers.FetchBoroughProjectsSerializer(get_sector_projects, many=True).data
            return Response(info, status=status.HTTP_200_OK)
        else:
            return Response({"details": f"No info about {sector}"}, status=status.HTTP_400_BAD_REQUEST)  

    
    @action(methods=["GET","POST", "PUT", "DELETE"], detail=False, url_path="weekly-reports",url_name="weekly-reports")
    def weekly_reports(self, request):
        authenticated_user = request.user
        payload = request.data
        # return
        
        if request.method == "POST":
            # serializer = serializers.WeeklyReportSerializer(
            #     data=payload, many=False)
            
            # if serializer.is_valid():

            for report in payload:
                try:
                    workplan = report['workplan']
                    activities = report['activities']

                    if not activities:
                        return Response({"details": f"Milestone Activity Progress Required!"}, status=status.HTTP_400_BAD_REQUEST) 
                    
                    for activity in activities:
                        try:
                            activity_id = activity['id']
                        except KeyError:
                            new_id = uuid.uuid4()
                            activity.update({"id": str(new_id)})
                            # print(new_id)
                    
                    try:
                        workplan = models.WorkPlan.objects.get(Q(id=workplan))
                    except (ValidationError, ObjectDoesNotExist):
                        return Response({"details": "Unknown workplan !"}, status=status.HTTP_400_BAD_REQUEST)
                    
                    report['workplan'] = workplan
                    
                except Exception as e:
                    print(e)
                    return Response({"details": f"All fields required!"}, status=status.HTTP_400_BAD_REQUEST) 

            
            with transaction.atomic():
                for report in payload:
                    workplan_exists = models.WeeklyReports.objects.filter(Q(workplan=report['workplan'])).first()

                    if workplan_exists:
                        activities = workplan_exists.activities
                        activities += report['activities']
                        workplan_exists.activities = activities
                        workplan_exists.save()
                        savedInstance = workplan_exists
                    else:
                        raw = {
                            "workplan" : report['workplan'],
                            "activities" : report['activities'],
                            "creator": authenticated_user
                        }

                        savedInstance = models.WeeklyReports.objects.create(**raw)
                                            

            user_util.log_account_activity(
                authenticated_user, authenticated_user, "Weekly Report created", f"Weekly Report Creation Executed: {savedInstance.id}")
            return Response('success', status=status.HTTP_200_OK)
            
            # else:
            #         return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        
        elif request.method == "PUT":
            serializer = serializers.UpdateWeeklyReportSerializer(
                data=payload, many=False)
            
            if serializer.is_valid():
                request_id = payload['request_id']
                workplan = payload['workplan']
                activities = payload['activities']

                for activity in activities:
                    try:
                        activity_id = activity['id']
                    except KeyError:
                        new_id = uuid.uuid4()
                        activity.update({"id": str(new_id)})
                        # print(new_id)    

                try:
                    workplan = models.WorkPlan.objects.get(Q(id=workplan))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown workplan !"}, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    WeeklyReports = models.WeeklyReports.objects.get(Q(id=request_id))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Report!"}, status=status.HTTP_400_BAD_REQUEST)
                
                
                with transaction.atomic():
                    # raw = {
                    #     "workplan" : workplan,
                    #     "activities" : activities,
                    #     "creator": authenticated_user
                    # }

                    WeeklyReports.workplan = workplan
                    WeeklyReports.activities = activities
                    WeeklyReports.creator = authenticated_user
                    WeeklyReports.save()


                    # models.WeeklyReports.objects.filter(Q(id=request_id)).update(**raw)
                                                

                user_util.log_account_activity(
                    authenticated_user, authenticated_user, "Weekly Report updated", f"Weekly Report updation Executed. Record id: {request_id}")
                return Response('success', status=status.HTTP_200_OK)
            
            else:
                    return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            rri_goal = request.query_params.get('rri_goal')
            if request_id:
                try:
                    report = models.WeeklyReports.objects.get(Q(id=request_id))
                    report = serializers.FetchWeeklyReportSerializer(report,many=False).data
                    return Response(report, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Request!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            elif rri_goal:
                try:
                    reports = models.WeeklyReports.objects.filter(Q(rri_goal=rri_goal) & Q(is_deleted=False)).order_by('-date_created')
                    reports = serializers.FetchWeeklyReportSerializer(reports,many=True).data
                    return Response(reports, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    reports = models.WeeklyReports.objects.filter(Q(is_deleted=False)).order_by('-date_created')
                    reports = serializers.FetchWeeklyReportSerializer(reports,many=True).data
                    return Response(reports, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                
        elif request.method == "DELETE":
            progress_id = request.query_params.get('progress_id')
            milestone_id = request.query_params.get('milestone_id')

            if not progress_id:
                return Response({"details": "Progress id  required !"}, status=status.HTTP_400_BAD_REQUEST)
            
            if not milestone_id:
                return Response({"details": "Milestone id  required !"}, status=status.HTTP_400_BAD_REQUEST)
            
            with transaction.atomic():
                try:
                    WeeklyReports = models.WeeklyReports.objects.get(Q(id=progress_id))

                    for activity in WeeklyReports.activities:
                        if activity['id'] == milestone_id:
                            WeeklyReports.activities.remove(activity)

                    WeeklyReports.save()

                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    print(e)
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)
                

    @action(methods=["GET","POST", "PUT", "PATCH", "DELETE"], detail=False, url_path="workplan",url_name="workplan")
    def workplan(self, request):
        authenticated_user = request.user
        payload = request.data
        
        if request.method == "POST":
            serializer = serializers.WWorkPlanSerializer(
                data=payload, many=False)
            
            if serializer.is_valid():
                milestone = payload['milestone']
                rri_goal = payload['rri_goal']
                steps = payload['steps']
                start_date = payload['start_date']
                end_date = payload['end_date']
                budget = payload['budget']
                plan_status = payload['status']
                remarks = payload['remarks']
                risks = payload['risks']
                collaborators = payload['collaborators']
                location = payload['location']

                try:
                    ward = location['ward']
                    ward = models.Ward.objects.get(id=ward)
                    ward = serializers.FetchWardSerializer(ward,many=False).data
                    location['ward'] = ward
                except Exception as e:
                    print(e)
                    return Response({"details": f"Ward required!"}, status=status.HTTP_400_BAD_REQUEST) 


                if not steps:
                    return Response({"details": f"Milestone Activities required!"}, status=status.HTTP_400_BAD_REQUEST) 
                

                # find difference in dates / validate dates
                days = shared_fxns.find_date_difference(start_date,end_date,'days')

                try:
                    budget = int(budget)
                except Exception as e:
                    return Response({"details": f"Invalid budget format !"}, status=status.HTTP_400_BAD_REQUEST) 
                            
                try:
                    days = int(days)
                except Exception as e:
                    return Response({"details": f"Invalid dates !"}, status=status.HTTP_400_BAD_REQUEST) 
                
                if days < 0:
                    return Response({"details": f"Invalid dates entered !"}, status=status.HTTP_400_BAD_REQUEST) 

                try:
                    rri_goal = models.RRIGoals.objects.get(Q(id=rri_goal))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown RRI Goal !"}, status=status.HTTP_400_BAD_REQUEST)
                
                
                with transaction.atomic():
                    raw = {
                        "start_date" : start_date,
                        "end_date" : end_date,
                        "milestone" : milestone,
                        "rri_goal" : rri_goal,
                        "steps" : steps,
                        "creator": authenticated_user,
                        "budget": budget,
                        "remarks": remarks,
                        "risks": risks,
                        "collaborators": collaborators,
                        "status": plan_status,
                        "location": location,
                    }

                    plan = models.WorkPlan.objects.create(**raw)
                                                

                user_util.log_account_activity(
                    authenticated_user, authenticated_user, "Workplan created", f"Workplan Creation Executed: {plan.id}")
                return Response('success', status=status.HTTP_200_OK)
            
            else:
                    return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        
        elif request.method == "PUT":
            serializer = serializers.UpdateWWorkPlanSerializer(
                data=payload, many=False)
            
            if serializer.is_valid():
                request_id = payload['request_id']
                milestone = payload['milestone']
                rri_goal = payload['rri_goal']
                steps = payload['steps']
                start_date = payload['start_date']
                end_date = payload['end_date']
                budget = payload['budget']
                plan_status = payload['status']
                remarks = payload['remarks']
                risks = payload['risks']
                collaborators = payload['collaborators']
                location = payload['location']

                try:
                    ward = location['ward']
                    ward = models.Ward.objects.get(id=ward)
                    ward = serializers.FetchWardSerializer(ward,many=False).data
                    location['ward'] = ward
                except Exception as e:
                    print(e)
                    return Response({"details": f"Ward required!"}, status=status.HTTP_400_BAD_REQUEST) 


                # find difference in dates / validate dates
                days = shared_fxns.find_date_difference(start_date,end_date,'days')
                            
                try:
                    days = int(days)
                except Exception as e:
                    return Response({"details": f"Invalid dates !"}, status=status.HTTP_400_BAD_REQUEST) 
                
                try:
                    budget = int(budget)
                except Exception as e:
                    return Response({"details": f"Invalid budget format !"}, status=status.HTTP_400_BAD_REQUEST) 
                
                if days < 0:
                    return Response({"details": f"Invalid dates entered !"}, status=status.HTTP_400_BAD_REQUEST) 

                try:
                    rri_goal = models.RRIGoals.objects.get(Q(id=rri_goal))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown RRI Goal!"}, status=status.HTTP_400_BAD_REQUEST)
                
                
                with transaction.atomic():
                    raw = {
                        "start_date" : start_date,
                        "end_date" : end_date,
                        "milestone" : milestone,
                        "rri_goal" : rri_goal,
                        "steps" : steps,
                        "creator": authenticated_user,
                        "budget": budget,
                        "remarks": remarks,
                        "status": plan_status,
                        "risks": risks,
                        "collaborators": collaborators,
                        "location": location,
                        
                    }

                    models.WorkPlan.objects.filter(Q(id=request_id)).update(**raw)
                                                

                user_util.log_account_activity(
                    authenticated_user, authenticated_user, "Workplan updated", f"Workplan updation Executed: {request_id}")
                return Response('success', status=status.HTTP_200_OK)
            
            else:
                    return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        
        elif request.method == "PATCH":
            serializer = serializers.PatchWorkPlanSerializer(
                data=payload, many=False)
            
            if serializer.is_valid():
                request_id = payload['request_id']
                percentage = payload['percentage']

                if int(percentage) > 100 or int(percentage) < 0:
                    return Response({"details": "Percentage is between 0 - 100"}, status=status.HTTP_400_BAD_REQUEST)
               
                
                with transaction.atomic():
                    raw = {
                        "percentage" : percentage
                    }

                    models.WorkPlan.objects.filter(Q(id=request_id)).update(**raw)
                                                

                user_util.log_account_activity(
                    authenticated_user, authenticated_user, "Workplan Percentage updated", f"Workplan Percentage updation Executed: {request_id}")
                return Response('success', status=status.HTTP_200_OK)
            
            else:
                    return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            rri_goal = request.query_params.get('rri_goal')
            if request_id:
                try:
                    worplan = models.WorkPlan.objects.get(Q(id=request_id))
                    worplan = serializers.FetchWorkPlanSerializer(worplan,many=False).data
                    return Response(worplan, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Request!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            elif rri_goal:
                try:
                    worplans = models.WorkPlan.objects.filter(Q(rri_goal=rri_goal) & Q(is_deleted=False)).order_by('-date_created')
                    worplans = serializers.FetchWorkPlanSerializer(worplans,many=True).data
                    return Response(worplans, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    worplans = models.WorkPlan.objects.filter(Q(is_deleted=False)).order_by('-date_created')
                    worplans = serializers.FetchWorkPlanSerializer(worplans,many=True).data
                    return Response(worplans, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
        
        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request !"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                try:
                    raw = {"is_deleted" : True}
                    models.WorkPlan.objects.filter(Q(id=request_id)).update(**raw)
                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)          

    @action(methods=["GET","POST", "PUT"], detail=False, url_path="results-chain",url_name="results-chain")
    def resultchain(self, request):
        authenticated_user = request.user
        payload = request.data
        
        if request.method == "POST":
            serializer = serializers.ResultChainSerializer(
                data=payload, many=False)
            
            if serializer.is_valid():
                workplan = payload['workplan']
                # activities = payload['activities']
                input = payload['input']
                output = payload['output']
                outcome = payload['outcome']
                impact = payload['impact']


                # if not activities:
                #     return Response({"details": f"Activities required !"}, status=status.HTTP_400_BAD_REQUEST) 
                if not input:
                    return Response({"details": f"Inputs required !"}, status=status.HTTP_400_BAD_REQUEST) 
                if not output:
                    return Response({"details": f"Outputs required !"}, status=status.HTTP_400_BAD_REQUEST) 
                if not outcome:
                    return Response({"details": f"Outcomes required !"}, status=status.HTTP_400_BAD_REQUEST) 
                if not impact:
                    return Response({"details": f"Impacts required !"}, status=status.HTTP_400_BAD_REQUEST) 

                try:
                    workplan = models.WorkPlan.objects.get(Q(id=workplan))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Goal !"}, status=status.HTTP_400_BAD_REQUEST)
                
                
                with transaction.atomic():
                    raw = {
                        "workplan" : workplan,
                        # "activities" : activities,
                        "creator": authenticated_user,
                        "input": input,
                        "output": output,
                        "outcome": outcome,
                        "impact": impact,
                    }

                    chain = models.ResultChain.objects.create(**raw)
                                                

                user_util.log_account_activity(
                    authenticated_user, authenticated_user, "ResultChain created", f"ResultChain Creation Executed: {chain.id}")
                return Response('success', status=status.HTTP_200_OK)
            
            else:
                    return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        
        elif request.method == "PUT":
            serializer = serializers.UpdateResultChainSerializer(
                data=payload, many=False)
            
            if serializer.is_valid():
                request_id = payload['request_id']
                workplan = payload['workplan']
                # activities = payload['activities']
                input = payload['input']
                output = payload['output']
                outcome = payload['outcome']
                impact = payload['impact']

                # if not activities:
                #     return Response({"details": f"Activities required !"}, status=status.HTTP_400_BAD_REQUEST) 

                try:
                    workplan = models.WorkPlan.objects.get(Q(id=workplan))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Goal!"}, status=status.HTTP_400_BAD_REQUEST)          
                
                
                with transaction.atomic():
                    raw = {
                        "workplan" : workplan,
                        # "activities" : activities,
                        "creator": authenticated_user,
                        "input": input,
                        "output": output,
                        "outcome": outcome,
                        "impact": impact,
                    }

                    models.ResultChain.objects.filter(Q(id=request_id)).update(**raw)
                                                

                user_util.log_account_activity(
                    authenticated_user, authenticated_user, "ResultChain updated", f"ResultChain updation Executed: {request_id}")
                return Response('success', status=status.HTTP_200_OK)
            
            else:
                    return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            workplan = request.query_params.get('workplan')
            if request_id:
                try:
                    chain = models.ResultChain.objects.get(Q(id=request_id))
                    chain = serializers.FetchResultChainSerializer(chain,many=False).data
                    return Response(chain, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Request!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            elif workplan:
                try:
                    chains = models.ResultChain.objects.filter(Q(workplan=workplan)).order_by('-date_created')
                    chains = serializers.FetchResultChainSerializer(chains,many=True).data
                    return Response(chains, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    chains = models.ResultChain.objects.all().order_by('-date_created')
                    chains = serializers.FetchResultChainSerializer(chains,many=True).data
                    return Response(chains, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
        

    @action(methods=["GET","POST", "PUT"], detail=False, url_path="evaluation",url_name="evaluation")
    def evaluation(self, request):
        authenticated_user = request.user
        payload = request.data
        
        if request.method == "POST":
            serializer = serializers.EvaluationSerializer(
                data=payload, many=False)
            
            if serializer.is_valid():
                rri_goal = payload['rri_goal']
                data = payload['data']
                total = 0

                if not data:
                    return Response({"details": f"Data required !"}, status=status.HTTP_400_BAD_REQUEST) 
                
                empty_keys = []
                for key, value in data.items():
                    for i, j in data[key].items():
                        if not j:
                            empty_keys.append(str(key + '=>' + i + ' is required !'))
                        else:
                            if i == 'score':
                                total = total + int(j)


                if empty_keys:
                    empty_keys = ', '.join(empty_keys)
                    return Response({"details": f"{empty_keys}"}, status=status.HTTP_400_BAD_REQUEST) 


                try:
                    rri_goal = models.RRIGoals.objects.get(Q(id=rri_goal))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown RRI Goal !"}, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    assigned = models.AssignedEvaluations.objects.get(Q(rri_goal=rri_goal) & Q(evaluator=request.user))
                except Exception as e:
                    print(e)
                    return Response({"details": "Evaluation not assigned !"}, status=status.HTTP_400_BAD_REQUEST) 
                
                
                with transaction.atomic():
                    data.update({"total":total})
                    raw = {
                        "rri_goal" : rri_goal,
                        "data" : data,
                        "evaluator": authenticated_user,
                    }

                    evaluation = models.Evaluation.objects.create(**raw)

                    assigned.is_evaluated = True
                    assigned.save()
                               

                user_util.log_account_activity(
                    authenticated_user, authenticated_user, "Evaluation created", f"Evaluation Creation Executed: {evaluation.id}")
                return Response('success', status=status.HTTP_200_OK)
            
            else:
                    return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        
        elif request.method == "PUT":
            serializer = serializers.UpdateEvaluationSerializer(
                data=payload, many=False)
            
            if serializer.is_valid():
                rri_goal = payload['rri_goal']
                data = payload['data']
                request_id = payload['request_id']
                total = 0

                if not data:
                    return Response({"details": f"Data required !"}, status=status.HTTP_400_BAD_REQUEST) 
                
                empty_keys = []
                for key, value in data.items():
                    for i, j in data[key].items():
                        if not j:
                            empty_keys.append(str(key + '=>' + i + ' is required !'))
                        else:
                            if i == 'score':
                                total = total + int(j)


                if empty_keys:
                    empty_keys = ', '.join(empty_keys)
                    return Response({"details": f"{empty_keys}"}, status=status.HTTP_400_BAD_REQUEST) 


                try:
                    rri_goal = models.RRIGoals.objects.get(Q(id=rri_goal))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown RRI Goal !"}, status=status.HTTP_400_BAD_REQUEST)
                

                with transaction.atomic():
                    data.update({"total":total})
                    raw = {
                        "rri_goal" : rri_goal,
                        "data" : data,
                        "evaluator": authenticated_user,
                    }

                    models.Evaluation.objects.filter(Q(id=request_id)).update(**raw)
                                                

                user_util.log_account_activity(
                    authenticated_user, authenticated_user, "Evaluation updated", f"Evaluation updation Executed: {request_id}")
                return Response('success', status=status.HTTP_200_OK)
            
            else:
                    return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            rri_goal = request.query_params.get('rri_goal')
            
            if request_id:
                try:
                    evaluation = models.Evaluation.objects.get(Q(id=request_id))
                    evaluation = serializers.FetchEvaluationSerializer(evaluation,many=False).data
                    return Response(evaluation, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Request!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            elif rri_goal:
                try:
                    evaluations = models.Evaluation.objects.filter(Q(rri_goal=rri_goal)).order_by('-date_created')
                    evaluations = serializers.FetchEvaluationSerializer(evaluations,many=True).data
                    return Response(evaluations, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    evaluations = models.Evaluation.objects.all().order_by('-date_created')
                    evaluations = serializers.FetchEvaluationSerializer(evaluations,many=True).data
                
                    return Response(evaluations, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=["GET","POST"], detail=False, url_path="assign-evaluation",url_name="assign-evaluation")
    def assign_evaluation(self, request):
        authenticated_user = request.user
        payload = request.data
        
        if request.method == "POST":
            serializer = serializers.AssignedEvaluationsSerializer(
                data=payload, many=False)
            
            if serializer.is_valid():
                
                evaluator = payload['evaluator']
                try:
                    rri_goal = payload['rri_goal']
                except Exception as e:
                    return Response({"details": "No goal selected !"}, status=status.HTTP_400_BAD_REQUEST)
                
                rri_goals = []
                evaluators = []

                # Check if it is a list
                if isinstance(rri_goal, list):
                    rri_goals += rri_goal
                else:
                    rri_goals.append(rri_goal)

                if isinstance(evaluator, list):
                    evaluators += evaluator
                else:
                    evaluators.append(evaluator)

                # print("evaluators1", evaluators)
                # print("\n\rri_goals1", rri_goals)
                
                try:
                    evaluators = get_user_model().objects.filter(Q(pk__in=evaluators))

                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Evaluator !"}, status=status.HTTP_400_BAD_REQUEST)
                
                try:
                    rri_goals = models.RRIGoals.objects.filter(Q(pk__in=rri_goals))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown RRI Goal !"}, status=status.HTTP_400_BAD_REQUEST)
                
                
                with transaction.atomic():
                    raw_instances = []

                    # Loop through each evaluator and goal
                    for evaluator in evaluators:
                        for goal in rri_goals:
                            # Check if the combination of evaluator and goal already exists
                            if not models.AssignedEvaluations.objects.filter(evaluator=evaluator, rri_goal=goal).exists():
                                # If it doesn't exist, add it to the list of instances to be saved
                                raw_instances.append({'rri_goal': goal, 'evaluator': evaluator})

                    print(raw_instances)
                    models.AssignedEvaluations.objects.bulk_create(
                        models.AssignedEvaluations(**data) for data in raw_instances
                    )
                                                
                for evaluator in evaluators:
                    user_util.log_account_activity(
                        evaluator, authenticated_user, "Evaluator Assigned", f"Evaluator assigning Executed, instances: {str(raw_instances)}")
                    
                return Response('success', status=status.HTTP_200_OK)
            
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
           
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            rri_goal = request.query_params.get('rri_goal')
            if request_id:
                try:
                    evaluation = models.AssignedEvaluations.objects.get(Q(id=request_id))
                    evaluation = serializers.FetchAssignedEvaluationsSerializer(evaluation,many=False).data
                    return Response(evaluation, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Request!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            elif rri_goal:
                try:
                    evaluations = models.AssignedEvaluations.objects.filter(Q(rri_goal=rri_goal)).order_by('-date_created')
                    evaluations = serializers.FetchAssignedEvaluationsSerializer(evaluations,many=True).data
                    return Response(evaluations, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    evaluations = models.AssignedEvaluations.objects.all().order_by('-date_created')
                    evaluations = serializers.FetchAssignedEvaluationsSerializer(evaluations,many=True).data
                    return Response(evaluations, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)


    @action(methods=["POST", "GET", "PUT", "DELETE"],
            detail=False,
            url_path="boroughs",
            url_name="boroughs")
    def borough(self, request):
        if request.method == "POST":
            payload = request.data
            serializer = serializers.GeneralNameSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                with transaction.atomic():
                    raw = {
                        "name": name
                    }
                    models.Borough.objects.create(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "PUT":
            payload = request.data
            serializer = serializers.UpdateDepartmentSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                request_id = payload['request_id']

                try:
                    sub_county = models.Borough.objects.get(Q(id=request_id))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown sub county!"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    sub_county.name = name
                    sub_county.save()

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            if request_id:
                try:
                    sub_county = models.Borough.objects.get(Q(id=request_id))
                    sub_county = serializers.FetchBoroughSerializer(sub_county,many=False).data
                    return Response(sub_county, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Sector!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    sub_counties = models.Borough.objects.filter(Q(is_deleted=False)).order_by('name')
                    sub_counties = serializers.FetchBoroughSerializer(sub_counties,many=True).data
                    return Response(sub_counties, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
         
        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request !"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                try:
                    raw = {"is_deleted" : True}
                    models.Borough.objects.filter(Q(id=request_id)).update(**raw)
                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)       

    
    @action(methods=["POST", "GET", "PUT", "DELETE"],
            detail=False,
            url_path="sub-counties",
            url_name="sub-counties")
    def sub_county(self, request):
        if request.method == "POST":
            payload = request.data
            serializer = serializers.CreateSubCountySerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                borough = payload['borough']

                try:
                    borough = models.Borough.objects.get(Q(id=borough))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown borough !"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    raw = {
                        "name": name,
                        "borough": borough
                    }
                    models.SubCounty.objects.create(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "PUT":
            payload = request.data
            serializer = serializers.UpdateSubCountySerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                borough = payload['borough']
                request_id = payload['request_id']

                try:
                    sub_county = models.SubCounty.objects.get(Q(id=request_id))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown sub county!"}, status=status.HTTP_400_BAD_REQUEST)

                try:
                    borough = models.Borough.objects.get(Q(id=borough))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown borough !"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    raw = {
                        "name": name,
                        "borough": borough
                    }
                    models.SubCounty.objects.filter(Q(id=request_id)).update(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            if request_id:
                try:
                    sub_county = models.SubCounty.objects.get(Q(id=request_id))
                    sub_county = serializers.FetchSubCountySerializer(sub_county,many=False).data
                    return Response(sub_county, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Sector!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    sub_counties = models.SubCounty.objects.filter(Q(is_deleted=False)).order_by('name')
                    sub_counties = serializers.FetchSubCountySerializer(sub_counties,many=True).data
                    return Response(sub_counties, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
        
        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request !"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                try:
                    raw = {"is_deleted" : True}
                    models.SubCounty.objects.filter(Q(id=request_id)).update(**raw)
                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)        

    @action(methods=["POST", "GET", "PUT", "DELETE"],
            detail=False,
            url_path="wards",
            url_name="wards")
    def wards(self, request):
        if request.method == "POST":
            payload = request.data
            serializer = serializers.CreateWardSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                sub_county = payload['sub_county']

                try:
                    sub_county = models.SubCounty.objects.get(Q(id=sub_county))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown sub county !"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    raw = {
                        "name": name,
                        "sub_county": sub_county
                    }
                    models.Ward.objects.create(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "PUT":
            payload = request.data
            serializer = serializers.UpdateWardSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                sub_county = payload['sub_county']
                request_id = payload['request_id']

                try:
                    ward = models.Ward.objects.get(Q(id=request_id))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Ward!"}, status=status.HTTP_400_BAD_REQUEST)

                try:
                    sub_county = models.SubCounty.objects.get(Q(id=sub_county))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown sub county !"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    raw = {
                        "name": name,
                        "sub_county": sub_county
                    }
                    models.Ward.objects.filter(Q(id=request_id)).update(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            if request_id:
                try:
                    ward = models.Ward.objects.get(Q(id=request_id))
                    ward = serializers.FetchWardSerializer(ward,many=False).data
                    return Response(ward, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Ward!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    wards = models.Ward.objects.filter(Q(is_deleted=False)).order_by('name')
                    wards = serializers.FetchWardSerializer(wards,many=True).data
                    return Response(wards, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
        
        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request !"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                try:
                    raw = {"is_deleted" : True}
                    models.Ward.objects.filter(Q(id=request_id)).update(**raw)
                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)        

    @action(methods=["POST", "GET", "PUT"],
            detail=False,
            url_path="estates",
            url_name="estates")
    def estates(self, request):
        if request.method == "POST":
            payload = request.data
            serializer = serializers.CreateEstateSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                ward = payload['ward']

                try:
                    ward = models.Ward.objects.get(Q(id=ward))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown sub county !"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    raw = {
                        "name": name,
                        "ward": ward
                    }
                    models.Estate.objects.create(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "PUT":
            payload = request.data
            serializer = serializers.UpdateEstateSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                ward = payload['ward']
                request_id = payload['request_id']

                try:
                    estate = models.Estate.objects.get(Q(id=request_id))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Estate!"}, status=status.HTTP_400_BAD_REQUEST)

                try:
                    ward = models.Ward.objects.get(Q(id=ward))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown ward !"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    raw = {
                        "name": name,
                        "ward": ward
                    }
                    models.Estate.objects.filter(Q(id=request_id)).update(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            if request_id:
                try:
                    estate = models.Estate.objects.get(Q(id=request_id))
                    estate = serializers.FetchEstateSerializer(estate,many=False).data
                    return Response(estate, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Estate!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    estates = models.Estate.objects.all().order_by('name')
                    estates = serializers.FetchEstateSerializer(estates,many=True).data
                    return Response(estates, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                
                
    @action(methods=["POST", "GET", "PUT", "DELETE"],
        detail=False,
        url_path="project-sub-category",
        url_name="project-sub-category")
    def project_sub_category(self, request):
        if request.method == "POST":
            payload = request.data
            serializer = serializers.GeneralNameSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                with transaction.atomic():
                    raw = {
                        "name":name
                    }
                    models.ProjectSubCategory.objects.create(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "PUT":
            payload = request.data
            serializer = serializers.UpdateDepartmentSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                request_id = payload['request_id']

                try:
                    subcategory = models.ProjectSubCategory.objects.get(Q(id=request_id))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Project Sub Categories!"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    subcategory.name = name
                    subcategory.save()

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            if request_id:
                try:
                    subcategory = models.ProjectSubCategory.objects.get(Q(id=request_id))
                    subcategory = serializers.FetchProjectSubCategorySerializer(subcategory,many=False).data
                    return Response(subcategory, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Project Sub Categories!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    sectors = models.ProjectSubCategory.objects.filter(Q(is_deleted=False)).order_by('name')
                    sectors = serializers.FetchProjectSubCategorySerializer(sectors,many=True).data
                    return Response(sectors, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)

        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request !"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                try:
                    raw = {"is_deleted" : True}
                    models.ProjectSubCategory.objects.filter(Q(id=request_id)).update(**raw)
                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)

    @action(methods=["POST", "GET", "PUT", "DELETE"],
        detail=False,
        url_path="financial_year_budget",
        url_name="financial_year_budget")
    
    def financial_year_budget(self, request):
        if request.method == "POST":
            payload = request.data
            serializer = serializers.CreateFinancialYearBudgetSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                Year = payload['Year']
                # StartDate = payload['StartDate']
                # EndDate = payload['EndDate']
                BudgetInKES = payload['BudgetInKES']
                
                if models.BudgetFinancialYear.objects.filter(Q(Year=Year)& Q(is_deleted=False)).exists():
                    return Response({"details": "The financial year already exists! Please enter a new financial year"}, status=status.HTTP_400_BAD_REQUEST)
                else:

                    with transaction.atomic():
                        raw = {
                            "Year": Year,
                            # "StartDate": StartDate,
                            # "EndDate": EndDate,
                            "BudgetInKES": BudgetInKES
                        }
                        models.BudgetFinancialYear.objects.create(**raw)
                        

                        return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            if request_id:
                try:
                    budget = models.BudgetFinancialYear.objects.get(Q(id=request_id))
                    budget = serializers.FetchFinancialYearBudgetSerializer(budget,many=False).data
                    return Response(budget, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Financial Year Budget..!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:                    
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    budgets = models.BudgetFinancialYear.objects.filter(Q(is_deleted=False)).order_by('Year')
                    budgets = serializers.FetchFinancialYearBudgetSerializer(budgets,many=True).data
                    return Response(budgets, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
        
        elif request.method == "PUT":
            payload = request.data
            request_id = payload.get('request_id')  # Ensure request_id is obtained from the payload
            serializer = serializers.UpdateFinancialYearBudgetSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                Year = payload['Year']
                # StartDate = payload['StartDate']
                # EndDate = payload['EndDate']
                BudgetInKES = payload['BudgetInKES']
                reason_for_changing_budget=payload['reason_for_changing_budget']
                authority_to_change=payload['authority_to_change']
                comments=payload['comments']                
                
                try:
                    budget = models.BudgetFinancialYear.objects.get(Q(id=request_id))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Financial Year Budget!"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    budget.Year = Year
                    # budget.StartDate = StartDate
                    # budget.EndDate = EndDate
                    budget.BudgetInKES = BudgetInKES
                    budget.reason_for_changing_budget = reason_for_changing_budget
                    budget.authority_to_change = authority_to_change
                    budget.comments=comments
                    budget.save()

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
        
        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request!"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                try:
                    raw = {"is_deleted" : True}
                    models.BudgetFinancialYear.objects.filter(Q(id=request_id)).update(**raw)
                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)
    
   # cabinet memo            
    @action(methods=["POST", "GET", "PUT", "DELETE"],
        detail=False,
        url_path="cabinet_memo",
        url_name="cabinet_memo")
    
    def cabinet_memo(self, request):
        if request.method == "POST":
            payload = request.data
            funds_source = payload.get('funds_source')
            otherFundsSource = payload.get('otherFundsSource')
            cabinetMemoFile = request.FILES.get('cabinetMemoFile')
            serializer = serializers.CreateCabinetMemoSerializer(
                data=payload, many=False)
           
            if serializer.is_valid():
                memoNumber = payload['memoNumber']
                title = payload['title']
                description = payload['description']
                # concept = payload['concept']
                goal = payload['goal']
                legal_implication = payload['legal_implication']
                area_of_focus = payload['area_of_focus'] 
                team_members = payload['team_members']
                funds_source= payload['funds_source']
                # otherFundsSource = payload['otherFundsSource']
                otherFundsSource = payload.get('otherFundsSource', None) if funds_source == 'Other' else None
                #new
                             
                
                if models.CabinetMemo.objects.filter(Q(memoNumber=memoNumber)).exists():
                    return Response({"details": "The memo already exists! Please create a new memo"}, status=status.HTTP_400_BAD_REQUEST)
                elif models.CabinetMemo.objects.filter(Q(description=description)).exists():

                    objective = models.CabinetMemo.objects.filter(Q(description=description))
                    obj = ""
                    for x in objective:
                        obj = x.memoNumber
                    return Response({"details": f"This objective already exists! Please ammend the following memo {obj}"}, status=status.HTTP_400_BAD_REQUEST)
                else:

                    with transaction.atomic():
                        raw = {
                            "memoNumber" : memoNumber,
                            "title": title,
                            "description": description,
                            # "concept": concept,
                            "goal": goal,
                            "legal_implication": legal_implication,
                            "funds_source":funds_source,
                            "otherFundsSource":otherFundsSource,
                            "cabinetMemoFile": cabinetMemoFile,
                            "area_of_focus":area_of_focus,
                            "team_members": team_members,
                            #new
                        }
                            
                        models.CabinetMemo.objects.create(**raw)
                        

                        return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            if request_id:
                try:
                    budget = models.CabinetMemo.objects.get(Q(id=request_id))
                    budget = serializers.FetchCabinetMemoSerializer(budget,many=False).data
                    return Response(budget, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Cabinet Memo!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:                    
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    cabinet_memos = models.CabinetMemo.objects.filter(Q(is_deleted=False)).order_by('memoNumber')
                    cabinet_memos = serializers.FetchCabinetMemoSerializer(cabinet_memos,many=True).data
                    return Response(cabinet_memos, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
        

        
        elif request.method == "PUT":
            payload = request.data
            request_id = payload.get('request_id')
            cabinetMemoFile = request.FILES.get('cabinetMemoFile')
            
            mutable_payload = payload.copy()
            
            if 'cabinetMemoFile' in mutable_payload and not cabinetMemoFile:
                del mutable_payload['cabinetMemoFile']
            
            serializer = serializers.UpdateCabinetMemoSerializer(
                data=mutable_payload, many=False)
                
            if serializer.is_valid():
                memoNumber = payload['memoNumber']
                title = payload['title']
                description = payload['description']
                # concept = payload['concept']
                goal = payload['goal']
                legal_implication = payload['legal_implication']
                funds_source = payload['funds_source']
                area_of_focus = payload['area_of_focus']
                team_members= payload['team_members']
                otherFundsSource = payload.get('otherFundsSource', None)
                
                try:
                    cabinet_memo = models.CabinetMemo.objects.get(Q(id=request_id))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown CECM memo!"}, status=status.HTTP_400_BAD_REQUEST)
                
                with transaction.atomic():
                    cabinet_memo.memoNumber = memoNumber
                    cabinet_memo.title = title
                    cabinet_memo.description = description
                    # cabinet_memo.concept = concept
                    cabinet_memo.goal = goal
                    cabinet_memo.legal_implication = legal_implication
                    cabinet_memo.funds_source = funds_source
                    cabinet_memo.area_of_focus = area_of_focus
                    cabinet_memo.team_members = team_members
                    if otherFundsSource is not None:
                        cabinet_memo.otherFundsSource = otherFundsSource
                    
                    if cabinetMemoFile:
                        cabinet_memo.cabinetMemoFile = cabinetMemoFile
                        
                    cabinet_memo.save()
                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
                
        elif request.method == "DELETE":
            request_id = request.query_params.get('request_id')
            if not request_id:
                return Response({"details": "Cannot complete request!"}, status=status.HTTP_400_BAD_REQUEST)
            with transaction.atomic():
                try:
                    raw = {"is_deleted" : True}
                    models.CabinetMemo.objects.filter(Q(id=request_id)).update(**raw)
                    return Response('200', status=status.HTTP_200_OK)     
                except Exception as e:
                    return Response({"details": "Unknown Id"}, status=status.HTTP_400_BAD_REQUEST)
                
    @action(methods=["POST", "GET", "PUT", "DELETE"],
        detail=False,
        url_path="cabinet_memo_approval",
        url_name="cabinet_memo_approval")
    
    def cabinet_memo_approval(self, request):
        if request.method == "POST":
            payload = request.data
            # request_id = payload.get('request_id')
            serializer = serializers.CreateCabinetMemoApprovalStatusSerializer(
                data=payload, many=False)
            
            
            
            if serializer.is_valid():
                
                request_id = payload.get('request_id')
                isApproved = payload['isApproved']
                isDeferred = payload['isDeferred']
                comments = payload['comments']
                
                # Validate and fetch the CabinetMemo based on memoNumber
                try:
                    memo = models.CabinetMemo.objects.get(Q(id=request_id))
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown Cabinet Memo!"}, status=status.HTTP_400_BAD_REQUEST)
                
                # # Ensure the approval/defer status hasn't been set before
                # if models.CabinetMemoApprovalStatus.objects.filter(memo=memo).exists():
                #     return Response({"details": "This memo already has an approval or defer status."}, status=status.HTTP_400_BAD_REQUEST)
                                
                with transaction.atomic():
                    
                    
                    raw = {
                        "memo" : memo,
                        "isApproved": isApproved,
                        "isDeferred": isDeferred,
                        "comments": comments,
                            
                        }
                    models.CabinetMemoApprovalStatus.objects.create(**raw)
                
                return Response({"details": "Approval status successfully recorded."}, status=status.HTTP_201_CREATED)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        elif request.method == "GET":
                        
            try:
                approval_statuses = models.CabinetMemoApprovalStatus.objects.all()
                serializer = serializers.FetchCabinetMemoApprovalStatusSerializer(approval_statuses, many=True)
                return Response(serializer.data, status=status.HTTP_200_OK)
            except Exception as e:
                print(e)
                return Response({"details": "Cannot fetch approval statuses at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                            
                        
                
                    
        
class ReportsViewSet(viewsets.ViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = models.Evaluation.objects.all().order_by('id')
    serializer_class = serializers.FetchEvaluationSerializer()
    search_fields = ['id', ]

    def get_queryset(self):
        return []

    @action(methods=["GET",],
            detail=False,
            url_path="evaluation",
            url_name="evaluation")
    def evaluation(self, request):
                    
        try:
            goals = models.Evaluation.objects.all().order_by('date_created')
            ids = list(set([goal.rri_goal.id for goal in goals]))
            # print(ids)
            goals = models.RRIGoals.objects.filter(Q(pk__in=ids))
            goals = serializers.FetchRRIGoalsSerializer(goals,many=True).data
            goals = sorted(goals, key=lambda d: d['evaluation_analytics']['average_score'], reverse=True) 
            return Response(goals, status=status.HTTP_200_OK)
        except (ValidationError, ObjectDoesNotExist):
            return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            print(e)
            return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)

class AnalyticsViewSet(viewsets.ViewSet):
    permission_classes = (IsAuthenticated,)
    # queryset = models.Evaluation.objects.all().order_by('id')
    # serializer_class = serializers.FetchEvaluationSerializer()
    # search_fields = ['id', ]

    def get_queryset(self):
        return []

    @action(methods=["GET",],
            detail=False,
            url_path="general",
            url_name="general")
    def general(self, request):
        main_projects = models.Wave.objects.filter(Q(type="MAIN") & Q(is_deleted=False)).count()
        sub_projects = models.Wave.objects.filter(Q(type="SUB") & Q(is_deleted=False)).count()
        objectives = models.RRIGoals.objects.filter(Q(is_deleted=False)).count()
        goals = models.ThematicArea.objects.filter(Q(is_deleted=False)).count()
        boroughs = models.Borough.objects.filter(Q(is_deleted=False)).count()
        # new
        budgets= models.BudgetFinancialYear.objects.filter(Q(is_deleted=False)).count()
        # end
        subcounties = models.SubCounty.objects.filter(Q(is_deleted=False)).count()
        wards = models.Ward.objects.filter(Q(is_deleted=False)).count()
        project_categories = models.ProjectSubCategory.objects.filter(Q(is_deleted=False)).count()
        sectors = models.Sector.objects.filter(Q(is_deleted=False)).count()
        subsectors = models.SubSector.objects.filter(Q(is_deleted=False)).count()
        directorates = models.Directorate.objects.filter(Q(is_deleted=False)).count()

        resp = {
            "main_projects": main_projects,
            "sub_projects": sub_projects,
            "objectives": objectives,
            "goals": goals,
            "budgets": budgets,  # new
            "boroughs": boroughs,
            "subcounties": subcounties,
            "wards": wards,
            "project_categories": project_categories,
            "sectors": sectors,
            "subsectors": subsectors,
            "directorates": directorates,
        }

        return Response(resp, status=status.HTTP_200_OK)

    @action(methods=["GET",],
            detail=False,
            url_path="budget",
            url_name="budget")
    def budget(self, request):

        # projects = models.Wave.objects.filter(Q(is_deleted=False))
        # sum_projects = 0
        # for project in projects:
        #     sum_projects += decimal(project.budget)
        total_budget = models.Wave.objects.filter(is_deleted=False).aggregate(total_budget=Sum('budget'))['total_budget'] or 0
        categories = models.ProjectSubCategory.objects.filter(is_deleted=False).values_list('id', flat=True)
        cat_list =[]
        labels = ["Total",]
        data = [total_budget,]
        financial_years = None
        for category in categories:
            labels.append(models.ProjectSubCategory.objects.get(id=category).name)
            data.append(models.Wave.objects.filter(is_deleted=False, sub_category=category).aggregate(total_budget=Sum('budget'))['total_budget'] or 0)
            # data = {
            #     "category" : models.ProjectSubCategory.objects.get(id=category).name,
            #     "budget" : models.Wave.objects.filter(is_deleted=False, sub_category=category).aggregate(total_budget=Sum('budget'))['total_budget'] or 0
            # }

            # cat_list.append(data)
            
            # Group budgets by financial year
       
        
            financial_years = models.Wave.objects.filter(is_deleted=False, sub_category=category).values('financial_year').annotate(yearly_budget=Sum('budget'))
            print(financial_years)
        financial_years_budgets = {}
        if financial_years:
            for fy in financial_years:
           
                year = fy['financial_year']
                financial_years_budgets = {}
                if year not in financial_years_budgets:
                    financial_years_budgets[year] = 0
                financial_years_budgets[year] += fy['yearly_budget']
            
            # Convert financial years budgets to sorted lists for labels and data
        sorted_years = sorted(financial_years_budgets.keys())
        yearly_labels = ["Total"] + sorted_years
        yearly_data = [total_budget] + [financial_years_budgets[year] for year in sorted_years]



        resp = {
            "labels": labels,
            "datasets": [
                {
                    "label": 'Budget',
                    "backgroundColor": '#f87979',
                    "data": data
                }
            ],
            "yearly_labels": yearly_labels,
            "yearly_data": yearly_data
        }

        return Response(resp, status=status.HTTP_200_OK)

class DepartmentViewSet(viewsets.ViewSet):
    permission_classes = (IsAuthenticated,)
    queryset = models.Department.objects.all().order_by('id')
    serializer_class = serializers.CreateDepartmentSerializer
    search_fields = ['id', ]

    def get_queryset(self):
        return []

    @action(methods=["POST", "GET", "PUT"],
            detail=False,
            url_path="department",
            url_name="department")
    def department(self, request):
        if request.method == "POST":
            payload = request.data
            serializer = serializers.GeneralNameSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                name = payload['name']
                with transaction.atomic():
                    raw = {
                        "name": name
                    }
                    models.Department.objects.create(**raw)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "PUT":
            payload = request.data
            serializer = serializers.UpdateDepartmentSerializer(
                data=payload, many=False)
            if serializer.is_valid():
                dept_id = payload['request_id']
                name = payload['name']
                with transaction.atomic():
                    try:
                        dept = models.Department.objects.get(id=dept_id)
                        dept.name = name
                        dept.save()
                    except (ValidationError, ObjectDoesNotExist):
                        return Response({"details": "Unknown department!"}, status=status.HTTP_400_BAD_REQUEST)

                    return Response("Success", status=status.HTTP_200_OK)
            else:
                return Response({"details": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
            
        elif request.method == "GET":
            request_id = request.query_params.get('request_id')
            if request_id:
                try:
                    department = models.Department.objects.get(Q(id=request_id))
                    department = serializers.FetchDepartmentSerializer(department,many=False).data
                    return Response(department, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Unknown department!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                try:
                    departments = models.Department.objects.all().order_by('name')
                    departments = serializers.FetchDepartmentSerializer(departments,many=True).data
                    return Response(departments, status=status.HTTP_200_OK)
                except (ValidationError, ObjectDoesNotExist):
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
                except Exception as e:
                    print(e)
                    return Response({"details": "Cannot complete request at this time!"}, status=status.HTTP_400_BAD_REQUEST)
